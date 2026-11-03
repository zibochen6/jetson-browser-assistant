"""Real local-service checks for clarification, single-task ownership and cancellation."""
from datetime import datetime
import json
import time

import httpx

from jetson_browser.config import ROOT, settings
from jetson_browser.llm import local_url

folder = ROOT / 'evidence' / ('state-checks-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
folder.mkdir(parents=True)
report = {}


def await_state(client, task_id, predicate, timeout=200):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get('/tasks/' + task_id).raise_for_status().json()
        if predicate(state):
            return state
        time.sleep(.2)
    raise TimeoutError('Expected task state did not arrive')


with httpx.Client(base_url=local_url(settings()['service_url']), trust_env=False, timeout=40) as client:
    if client.get('/health').raise_for_status().json()['active_tasks']:
        raise SystemExit('Another task is active')
    task_id = client.post('/tasks', json={'request': '帮我查机票', 'keep_open': True}).raise_for_status().json()['id']
    try:
        state = await_state(client, task_id, lambda s: s['status'] != 'RUNNING')
        assert state['status'] == 'NEEDS_USER' and state['browser_actions'] == 0
        report['clarification'] = {'id': task_id, 'status': state['status'], 'missing': state.get('missing'), 'browser_actions': 0}
        concurrent = client.post('/tasks', json={'request': '帮我查机票', 'keep_open': True})
        assert concurrent.status_code == 409
        report['single_task_guard_status'] = concurrent.status_code
        time.sleep(2)
        client.post('/tasks/' + task_id + '/resume', json={'additional_information': '深圳到上海，下周五，单程，1名成人，经济舱，优先直飞和低价'}).raise_for_status()
        state = await_state(client, task_id, lambda s: bool(s.get('task')) or s['status'] not in ['RUNNING'])
        assert state.get('task', {}).get('origin') == '深圳' and state['task']['destination'] == '上海'
        assert state['human_wait_seconds'] >= 2
        report['resume'] = {'parsed_task': state['task'], 'human_wait_seconds': state['human_wait_seconds']}
    finally:
        cancelled = client.post('/tasks/' + task_id + '/cancel').raise_for_status().json()
    assert cancelled['status'] == 'CANCELLED'
    time.sleep(2)
    after = client.get('/tasks/' + task_id).raise_for_status().json()
    assert after['browser_actions'] == cancelled['browser_actions'] and after['status'] == 'CANCELLED'
    report['cancel_after_resume'] = {'id': task_id, 'status': after['status'], 'browser_actions': after['browser_actions'], 'no_actions_after_cancel': True}
    task_id = client.post('/tasks', json={'request': '帮我查机票', 'keep_open': True}).raise_for_status().json()['id']
    try:
        state = await_state(client, task_id, lambda s: s['status'] != 'RUNNING')
        assert state['status'] == 'NEEDS_USER'
        time.sleep(2)
    finally:
        state = client.post('/tasks/' + task_id + '/cancel').raise_for_status().json()
    assert state['status'] == 'CANCELLED' and state['human_wait_seconds'] >= 2 and state['browser_actions'] == 0
    report['cancel_while_waiting'] = {'id': task_id, 'status': state['status'], 'human_wait_seconds': state['human_wait_seconds'], 'browser_actions': 0}
report['passed'] = True
(folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(folder, flush=True)
