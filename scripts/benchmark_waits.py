"""Compare real-site engine runs with identical empty profiles and warm local models.

No videos, model reloads, MTP switches, user-profile edits or simulated flights.
"""
import argparse
import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--code-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--label', required=True)
args = parser.parse_args()
code_root = args.code_root.resolve()
os.environ['JETSON_BROWSER_ROOT'] = str(code_root)
sys.path.insert(0, str(code_root / 'src'))

import httpx
from jetson_browser.browser import Browser
from jetson_browser.config import settings
from jetson_browser.runner import run_task
from jetson_browser.service import Session
from jetson_browser.trace import Trace

CASES = [
    ('Shenzhen', 'Shanghai', '2026-11-13'),
    ('Guangzhou', 'Beijing', '2026-11-20'),
    ('Shanghai', 'Shenzhen', '2026-11-21'),
]


async def main():
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'label': args.label, 'started_at': datetime.now().astimezone().isoformat(),
              'method': 'Real visible browser engine; empty isolated profile per case; warm unchanged models; no video; includes final artifacts; excludes CLI rendering',
              'source_sha256': {str(p.relative_to(code_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((code_root / 'src').rglob('*.py'))},
              'models': {}, 'results': []}
    config = settings()
    for model in ['laya', 'qwen']:
        response = httpx.get(config[model + '_url'] + '/health', timeout=5, trust_env=False)
        response.raise_for_status()
        report['models'][model] = response.json()
    path = args.output / (args.label + '.json')
    for index, (origin, destination, day) in enumerate(CASES):
        health = httpx.get(config['service_url'] + '/health', timeout=5, trust_env=False).json()
        if health['active_tasks']:
            raise RuntimeError('A user task is active; benchmark stopped without interrupting it')
        profile = args.output / 'profiles' / args.label / str(index)
        if profile.exists():
            raise RuntimeError('Profile already exists; use a new output directory or label')
        profile.mkdir(parents=True)
        request = (f'Find one-way flights from {origin} to {destination} on {day} for 1 adult in economy. '
                   'Nonstop only, lowest price first. Show up to 3 options and open the fare options for one matching flight.')
        trace = Trace(request, True, submitted_at=time.time(), timing_scope='after_preload', record_video=False)
        session = Session(trace, True)
        browser = Browser(profile_dir=profile)
        worker = asyncio.create_task(run_task(session, browser))
        start = time.monotonic()
        interrupted_status = None
        print(f'{args.label} {index+1}/3: {origin} -> {destination}; run {trace.id}', flush=True)
        try:
            while not worker.done():
                if trace.state['status'] == 'NEEDS_USER' or time.monotonic() - start > 720:
                    interrupted_status = trace.state['status']
                    worker.cancel()
                await asyncio.sleep(.25)
            await worker
        finally:
            await browser.close()
        state = trace.state
        task = state.get('task', {})
        correct = all(task.get(k) == v for k, v in dict(origin=origin, destination=destination, departure_date=day,
                      adults=1, cabin='economy', trip_type='one_way', direct_only=True, price_preferred=True).items())
        flights = state.get('candidates', [])
        passed = bool(state['status'] == 'SUCCEEDED' and correct and flights and state.get('sort_proof')
                      and all(f.get('route_verified') and f.get('departure_date') == day and f.get('nonstop') is True for f in flights)
                      and (state.get('booking_options_opened') or state.get('details_opened')))
        row = {k: state.get(k) for k in ['id', 'status', 'total_seconds', 'browser_actions', 'model_decision_seconds',
               'task_parse_seconds', 'field_generation_seconds', 'page_interaction_seconds', 'results_wait_seconds',
               'observation_seconds', 'action_execution_seconds', 'postcondition_wait_seconds', 'run_directory', 'message']}
        row.update(passed=passed, conditions_correct=correct, interrupted_status=interrupted_status,
                   request=request, origin=origin, destination=destination, departure_date=day)
        report['results'].append(row)
        report['passed'] = sum(r['passed'] for r in report['results'])
        report['median_seconds'] = statistics.median(r['total_seconds'] for r in report['results'])
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report['finished_at'] = datetime.now().astimezone().isoformat()
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(path, flush=True)


asyncio.run(main())
