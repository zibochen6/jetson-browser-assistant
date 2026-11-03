from datetime import datetime
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
import uuid
from zoneinfo import ZoneInfo

from .config import ROOT


class Trace:
    def __init__(self, request, keep_open, submitted_at=None, startup=None, run_id=None,
                 timing_scope='legacy', record_video=None, scene='trip', runs_root='runs'):
        self.id = run_id or datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
        self.folder = ROOT / runs_root / self.id
        self.folder.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.submitted_at = submitted_at or time.time()
        self.events = []
        self.operations = {}
        self.state = {'id': self.id, 'status': 'RUNNING', 'request': request, 'keep_open': keep_open,
                      'phase': 'parse', 'message': 'Parsing the flight request', 'startup_seconds': startup or {},
                      'timing_scope': timing_scope, 'record_video': record_video,
                      'browser_actions': 0, 'model_decision_seconds': 0.0, 'field_generation_seconds': 0.0,
                      'laya_decision_seconds': 0.0, 'qwen_recovery_seconds': 0.0,
                      'observation_seconds': 0.0, 'action_execution_seconds': 0.0,
                      'postcondition_wait_seconds': 0.0, 'results_wait_seconds': 0.0,
                      'control_readiness_seconds': 0.0,
                      'human_takeover': False, 'human_wait_seconds': 0.0, 'site_adapters': [],
                      'query_completed': False, 'details_opened': False, 'booking_options_opened': False, 'booking_entry_opened': False,
                      'assistant_created_order': False, 'assistant_paid_or_ticketed': False,
                      'candidates': [], 'current_url': None, 'run_directory': str(self.folder)}
        self.state['browser_open'] = False
        self.state['scene'] = scene
        if scene != 'trip':
            self.state['message'] = 'Reading the current whiteboard'
        self.state['submitted_at'] = self.submitted_at
        self.state['telemetry_version'] = 1
        self.state['active_operations'] = []
        self.event('user', 'Task submitted', request=request)
        self.save()

    def event(self, actor, message, **data):
        event = {'sequence': len(self.events), 'timestamp': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
                 'elapsed_seconds': max(0, time.time() - self.submitted_at),
                 'actor': actor, 'message': message, **data}
        event['metrics'] = {k: self.state.get(k) for k in (
            'phase', 'browser_actions', 'laya_decision_seconds', 'task_parse_seconds',
            'field_generation_seconds', 'qwen_recovery_seconds', 'results_wait_seconds',
            'query_completed', 'details_opened', 'booking_options_opened', 'human_wait_seconds')}
        self.events.append(event)
        with (self.folder / 'events.jsonl').open('a') as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + '\n')
        self.state['message'] = message
        self.save()
        return event

    @contextmanager
    def operation(self, stage, actor, message, **data):
        """Observe existing work without changing model inputs or execution policy."""
        operation_id = uuid.uuid4().hex
        started = time.perf_counter()
        self.operations[operation_id] = {'operation_id': operation_id, 'stage': stage,
                                         'actor': actor, 'message': message}
        self.state['active_operations'] = list(self.operations.values())
        self.event(actor, message, event_type='operation', transition='start',
                   operation_id=operation_id, stage=stage, **data)
        outcome = 'completed'
        try:
            yield data
        except BaseException:
            outcome = 'interrupted'
            raise
        finally:
            self.operations.pop(operation_id, None)
            self.state['active_operations'] = list(self.operations.values())
            self.event(actor, message, event_type='operation', transition='end', outcome=outcome,
                       operation_id=operation_id, stage=stage,
                       duration_seconds=time.perf_counter() - started, **data)

    def save(self):
        self.state['total_seconds'] = max(0, self.state.get('finished_at', time.time()) - self.submitted_at)
        target = self.folder / 'result.json'
        temp = target.with_suffix('.json.tmp')
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2, default=str))
        os.replace(temp, target)

    def snapshot(self, observation, step):
        data = {'observation_id': observation.id, 'page_id': observation.page_id, **observation.data,
                'full_visible_text': observation.text}
        (self.folder / f'observation-{step:03d}.json').write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def set_status(self, status, message, **extra):
        if status not in ['RUNNING', 'NEEDS_USER']:
            self.state.setdefault('finished_at', time.time())
        self.state.update(status=status, **extra)
        self.event('service', message, status=status)

    def adapter(self, name):
        if name not in self.state['site_adapters']:
            self.state['site_adapters'].append(name)
