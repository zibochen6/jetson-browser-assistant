"""Submit a real task and report actual endpoint status; no substitute actions."""
import json
import sys
import time
import httpx

request = ' '.join(sys.argv[1:]) or 'Draw three labeled boxes: Camera on the left, Jetson in the center, and Display on the right. Connect Camera to Jetson and Jetson to Display with arrows.'
base = 'http://127.0.0.1:8793'
with httpx.Client(base_url=base, trust_env=False, timeout=10) as c:
    r = c.post('/tasks', json={'request': request, 'submitted_at': time.time()})
    r.raise_for_status()
    run = r.json()['id']
    print(run, flush=True)
    previous = None
    while True:
        d = c.get('/tasks/' + run).json()
        msg = (d['status'], d.get('browser_actions'), d['message'])
        if msg != previous:
            print(msg, flush=True)
            previous = msg
        if d['status'] != 'RUNNING':
            print(json.dumps({k: d.get(k) for k in ('id', 'status', 'total_seconds', 'laya_calls', 'task_parse_seconds', 'ui_seconds', 'save_error')}), flush=True)
            break
        time.sleep(1)
