"""Run a frozen, sequential real-site suite; failures and manual waits are retained."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

import httpx

from jetson_browser.config import ROOT, settings
from jetson_browser.llm import local_url

parser = argparse.ArgumentParser()
parser.add_argument('cases', type=Path)
parser.add_argument('--name', default='g2')
args = parser.parse_args()
cases = json.loads(args.cases.read_text())
folder = ROOT / 'evidence' / (args.name + '-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
folder.mkdir(parents=True)
files = sorted((ROOT / 'src').rglob('*.py'))
source = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
report = {'cases_sha256': hashlib.sha256(args.cases.read_bytes()).hexdigest(), 'source_sha256': source,
          'started_at': datetime.now().astimezone().isoformat(), 'cases': cases, 'results': []}
report_path = folder / 'report.json'
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

with httpx.Client(base_url=local_url(settings()['service_url']), timeout=40, trust_env=False) as client:
    health = client.get('/health').raise_for_status().json()
    if health['active_tasks']:
        raise SystemExit('Another task is active; suite not started')
    for index, case in enumerate(cases, 1):
        start = time.time()
        response = client.post('/tasks', json={'request': case['request'], 'keep_open': True,
                               'open_details': case.get('open_details', False), 'submitted_at': start})
        response.raise_for_status()
        task_id = response.json()['id']
        print(f'{index}/{len(cases)} {task_id}: {case["request"]}', flush=True)
        while True:
            state = client.get('/tasks/' + task_id).raise_for_status().json()
            if state['status'] != 'RUNNING' or time.time() - start > 720:
                break
            time.sleep(1)
        observed_status = state['status']
        if observed_status in ['RUNNING', 'NEEDS_USER']:
            client.post('/tasks/' + task_id + '/cancel').raise_for_status()
            state = client.get('/tasks/' + task_id).raise_for_status().json()
        parsed = state.get('task', {})
        conditions = all(parsed.get(k) == v for k, v in case['expected'].items())
        flights = state.get('candidates', [])
        independent = bool(conditions and flights and all(f.get('route_verified') and f.get('departure_date') == case['expected']['departure_date'] for f in flights))
        result = {'id': task_id, 'observed_status': observed_status, 'final_status': state['status'],
                  'passed': observed_status == 'SUCCEEDED' and state.get('query_completed', False) and independent,
                  'conditions_correct': conditions, 'candidate_count': len(flights),
                  'query_completed': state.get('query_completed', False), 'sort_verified': bool(state.get('sort_proof')),
                  'details_opened': state.get('details_opened', False), 'booking_options_opened': state.get('booking_options_opened', False),
                  'seconds': state.get('total_seconds'), 'browser_actions': state.get('browser_actions'),
                  'human_takeover': state.get('human_takeover'), 'message': state.get('message'),
                  'run_directory': state.get('run_directory')}
        report['results'].append(result)
        report['passed'] = sum(r['passed'] for r in report['results'])
        report['completed'] = len(report['results'])
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False), flush=True)
report['finished_at'] = datetime.now().astimezone().isoformat()
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(report_path, flush=True)
