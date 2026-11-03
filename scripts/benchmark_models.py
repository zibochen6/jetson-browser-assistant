"""Paired MTP benchmark on the same Jetson, weights, seed, schema and requests.

Runs real browser tasks as well as parser requests. Never run alongside another task.
"""
import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import threading
import time

import httpx

from jetson_browser.config import ROOT, settings
from jetson_browser.llm import Qwen, local_url
from jetson_browser.services import ready, spawn, start_model, stop, wait_model

CASES = [
    ('查找下周五深圳到上海的单程机票，1名成人，经济舱，优先直飞和低价',
     {'origin': '深圳', 'destination': '上海', 'departure_date': '2026-11-13', 'direct_only': False, 'direct_preferred': True, 'price_preferred': True}),
    ('查询2026年11月20日广州到北京的单程机票，1名成人，经济舱，优先直飞和低价',
     {'origin': '广州', 'destination': '北京', 'departure_date': '2026-11-20', 'direct_only': False, 'direct_preferred': True, 'price_preferred': True}),
    ('查询2026-11-21上海到深圳的单程机票，1名成人，经济舱，只要直飞，按低价优先',
     {'origin': '上海', 'destination': '深圳', 'departure_date': '2026-11-21', 'direct_only': True, 'price_preferred': True}),
]
BROWSER_CASES = CASES[-1:]  # One paired hard-nonstop/fare-options task; main Laya acceptance is separate.


class Memory:
    """Jetson unified memory: sampled whole-device RAM; process RSS is reported separately."""
    def __init__(self):
        self.peak_used_mib = 0
        self.event = threading.Event()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def sample(self):
        while not self.event.is_set():
            values = {l.split(':')[0]: int(l.split()[1]) for l in Path('/proc/meminfo').read_text().splitlines()}
            self.peak_used_mib = max(self.peak_used_mib, (values['MemTotal'] - values['MemAvailable']) / 1024)
            self.event.wait(.2)

    def start(self):
        self.thread.start()

    def finish(self):
        self.event.set()
        self.thread.join()
        return self.peak_used_mib


def correct(task, expected):
    actual = task.model_dump(mode='json') if task else {}
    expected = {**expected, 'adults': 1, 'cabin': 'economy', 'trip_type': 'one_way'}
    checks = {k: actual.get(k) == v for k, v in expected.items()}
    return checks, actual


async def main():
    folder = ROOT / 'evidence' / ('mtp-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    report = {'weight_manifest': json.loads((ROOT / 'manifest-Qwen3.5-4B-MTP-GGUF.json').read_text()),
              'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT / 'src').rglob('*.py'))},
              'llama_commit': (ROOT / 'runtime/llama-commit.txt').read_text().strip(),
              'power_mode': subprocess.check_output(['nvpmodel', '-q'], text=True),
              'startup_measure': 'new model process; OS file cache not flushed; not a cold boot',
              'browser_initial_state': 'same dedicated profile snapshot restored before each mode; execution service restarted; sequential cases within each mode',
              'cases': CASES, 'browser_cases': BROWSER_CASES, 'temperature': .1, 'seed': 42, 'context': settings()['context_size'],
              'draft_depth': settings()['draft_depth'], 'memory_measure': 'MemTotal-MemAvailable sampled every 0.2s, whole Jetson incl. Laya/browser/OS; not dedicated VRAM',
              'modes': {}}
    path = folder / 'report.json'
    def save():
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    with httpx.Client(base_url=local_url(settings()['service_url']), timeout=40, trust_env=False) as client:
        if client.get('/health').raise_for_status().json()['active_tasks']:
            raise RuntimeError('Another browser task is active')
        stop('service')
        profile = ROOT / 'profile'
        if profile.is_symlink():
            raise RuntimeError('Benchmark will not replace a symlinked profile')
        initial_profile = folder / 'initial-profile'
        shutil.copytree(profile, initial_profile, symlinks=True, ignore=shutil.ignore_patterns('Singleton*'))
        for enabled in [False, True]:
            name = 'on' if enabled else 'off'
            stop('service')
            shutil.rmtree(profile)
            shutil.copytree(initial_profile, profile, symlinks=True)
            stop('qwen')
            start = time.perf_counter()
            start_model('qwen', mtp=enabled)
            wait_model('qwen')
            mode = {'startup_seconds': time.perf_counter() - start, 'parser': [], 'browser': []}
            report['modes'][name] = mode
            print(f'MTP {name} loaded: {mode["startup_seconds"]:.2f}s', flush=True)
            # First request is recorded separately rather than mixed into warm latency.
            _, mode['first_request'] = await Qwen().parse(CASES[0][0])
            save()
            for request, expected in CASES:
                memory = Memory()
                memory.start()
                try:
                    task, timing = await Qwen().parse(request)
                    checks, actual = correct(task, expected)
                    row = {'checks': checks, 'correct': all(checks.values()), 'actual': actual, **timing}
                except Exception as error:
                    row = {'correct': False, 'error': str(error)}
                row['peak_device_used_mib'] = memory.finish()
                mode['parser'].append(row)
                print(name, 'parser', row.get('seconds'), row['correct'], flush=True)
                save()
            spawn('service', [sys.executable, '-m', 'uvicorn', 'jetson_browser.service:app', '--host', '127.0.0.1', '--port', '8790'])
            deadline = time.monotonic() + 30
            while not ready(settings()['service_url']):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Execution service did not restart')
                await asyncio.sleep(.2)
            for request, expected in BROWSER_CASES:
                memory = Memory()
                memory.start()
                start = time.time()
                task_id = client.post('/tasks', json={'request': request, 'keep_open': True, 'open_details': True, 'submitted_at': start}).raise_for_status().json()['id']
                while True:
                    state = client.get('/tasks/' + task_id).raise_for_status().json()
                    if state['status'] != 'RUNNING' or time.time() - start > 720:
                        break
                    await asyncio.sleep(1)
                observed = state['status']
                if observed in ['RUNNING', 'NEEDS_USER']:
                    client.post('/tasks/' + task_id + '/cancel').raise_for_status()
                    state = client.get('/tasks/' + task_id).raise_for_status().json()
                conditions = all(state.get('task', {}).get(k) == v for k, v in expected.items())
                success = observed == 'SUCCEEDED' and conditions and state.get('query_completed') and (state.get('details_opened') or state.get('booking_options_opened'))
                row = {k: state.get(k) for k in ['id', 'message', 'total_seconds', 'browser_actions', 'human_takeover', 'query_completed', 'details_opened', 'booking_options_opened', 'run_directory']}
                row.update(observed_status=observed, passed=bool(success), conditions_correct=conditions,
                           peak_device_used_mib=memory.finish())
                mode['browser'].append(row)
                print(name, 'browser', task_id, observed, row['total_seconds'], flush=True)
                save()
            process = json.loads((ROOT / 'runtime/qwen.process.json').read_text())
            mode['qwen_process_arguments'] = process['args']
            mode['qwen_process_status'] = Path('/proc') .joinpath(str(process['pid']), 'status').read_text()
            mode['parser_correct'] = sum(r['correct'] for r in mode['parser'])
            mode['parser_fields_correct'] = sum(sum(r.get('checks', {}).values()) for r in mode['parser'])
            mode['parser_fields_total'] = sum(len(r.get('checks', {})) for r in mode['parser'])
            mode['parser_median_seconds'] = statistics.median(r['seconds'] for r in mode['parser'] if 'seconds' in r)
            mode['browser_successes'] = sum(r['passed'] for r in mode['browser'])
            mode['browser_median_seconds'] = statistics.median(r['total_seconds'] for r in mode['browser'])
            save()
    print(path, flush=True)


asyncio.run(main())
