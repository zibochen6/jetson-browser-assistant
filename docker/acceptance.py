#!/usr/bin/env python3
"""Actual model/UI task checks inside the image; use a new acceptance data volume."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import time
import urllib.request


def call(port, path, body=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f'http://127.0.0.1:{port}' + path, data=data,
                                     headers={'Content-Type': 'application/json'})
    with opener.open(request, timeout=30) as response:
        return json.load(response)


def task(port, request):
    submitted = call(port, '/tasks', {'request': request, 'keep_open': True, 'record_video': False})
    ident = submitted.get('id') or submitted.get('task_id')
    deadline = time.monotonic() + 660
    while True:
        result = call(port, '/tasks/' + ident)
        if result['status'] not in ('RUNNING', 'NEEDS_USER'):
            return result
        if result['status'] == 'NEEDS_USER' or time.monotonic() > deadline:
            original = result
            call(port, f'/tasks/{ident}/cancel', {})
            # Keep the original blocking outcome instead of calling cancellation success.
            return original
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scene', choices=['flights', 'whiteboard', 'restore'])
    args = parser.parse_args()
    folder = Path('/data/evidence')
    folder.mkdir(exist_ok=True)
    rows = []
    if args.scene == 'flights':
        for offset, origin, destination in [(14,'Shenzhen','Shanghai'), (15,'Guangzhou','Beijing'), (16,'Shanghai','Shenzhen')]:
            day = (date.today() + timedelta(days=offset)).isoformat()
            request = f'Find one-way flights from {origin} to {destination} on {day} for 1 adult in economy. Nonstop only, lowest price first. Show up to 3 options and open the fare options for one matching flight.'
            result = task(8790, request)
            row = {k:result.get(k) for k in ['id','status','message','total_seconds','browser_actions',
                'query_completed','booking_options_opened','details_opened','sort_proof']}
            row['candidate_count'] = len(result.get('candidates') or [])
            row['route'] = origin + ' -> ' + destination
            rows.append(row)
            print(json.dumps(row), flush=True)
    else:
        from jetson_browser.whiteboard_cli import ensure_service
        ensure_service()
        requests = ['Make Jetson green. Keep everything else.'] if args.scene == 'restore' else [
            'Draw three labeled boxes: Camera on the left, Jetson in the center, and Display on the right. Connect Camera to Jetson and Jetson to Display with arrows.',
            'Make Jetson green. Add a box labeled Robot Arm below Jetson and connect Jetson to Robot Arm. Keep everything else.']
        for request in requests:
            result = task(8793, request)
            row = {k:result.get(k) for k in ['id','status','message','total_seconds','browser_actions','laya_calls','scene_verified']}
            rows.append(row)
            print(json.dumps(row), flush=True)
        board = call(8793, '/board')
        (folder / ('docker-' + args.scene + '-board.json')).write_text(json.dumps(board, indent=2))
    (folder / ('docker-' + args.scene + '-acceptance.json')).write_text(json.dumps(rows, indent=2) + '\n')
    if not all(row['status'] == 'SUCCEEDED' for row in rows):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
