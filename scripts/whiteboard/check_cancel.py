"""Real cancellation while a mouse gesture is held, on an idle test board."""
import json
import time
import httpx
from jetson_browser.config import ROOT

with httpx.Client(base_url='http://127.0.0.1:8793',trust_env=False,timeout=40) as client:
    assert not client.get('/health').json()['active_tasks']
    before=client.get('/board').json()
    run=client.post('/tasks',json={'request':'Add a box labeled CancelTest below Display. Keep everything else.',
                                'submitted_at':time.time()}).json()['id']
    down_seen=False
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        state=client.get('/tasks/'+run).json()
        if state['status']!='RUNNING':
            break
        if any(op['stage']=='execute' for op in state['active_operations']):
            raw=client.get('/board').json()
            if raw['appState'].get('cursorButton')=='down':
                down_seen=True
                break
        time.sleep(.005)
    result=client.post(f'/tasks/{run}/cancel').json()
    after=client.get('/board').json()
    report={'run_id':run,'down_seen':down_seen,'status':result['status'],
        'cursor_after':after['appState'].get('cursorButton'),
        'previous_element_ids_preserved':{e['id'] for e in before['elements']} <= {e['id'] for e in after['elements']},
        'actual_before':before,'actual_after':after}
    (ROOT/'runtime/whiteboard-cancel-check.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:report[k] for k in ('run_id','down_seen','status','cursor_after','previous_element_ids_preserved')}))
    assert down_seen and report['status']=='CANCELLED' and report['cursor_after']=='up' and report['previous_element_ids_preserved']
