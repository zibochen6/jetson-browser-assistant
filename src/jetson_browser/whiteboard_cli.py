"""English interactive entrypoint; models and board outlive the terminal."""
import argparse
import asyncio
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import time

import httpx
from rich.console import Console
from rich.live import Live
from rich.text import Text

from .config import ROOT, settings
from .services import check_port, ready, spawn, start_model, stop, wait_model

BASE = 'http://127.0.0.1:8793'
console = Console()


def warm_models():
    from .llm import Qwen, laya_decide
    from .whiteboard_scene import digest
    markers = {}
    for name in ('laya', 'qwen'):
        path = ROOT / 'runtime' / (name + '.process.json')
        markers[name] = json.loads(path.read_text()).get('started_at') if path.exists() else None
    marker = digest(markers)
    record = ROOT / 'runtime/whiteboard-warmup.json'
    if record.exists() and json.loads(record.read_text()).get('model_process_marker') == marker:
        return

    async def warm():
        q, timing = await Qwen().json('Startup warmup only. Return ready=true.', {},
            {'type':'object','properties':{'ready':{'type':'boolean'}},'required':['ready'],'additionalProperties':False}, max_tokens=16)
        page = {'url':'about:blank','title':'Startup warmup (synthetic, not acceptance evidence)',
            'text':'Choose the Green button.', 'actions':[{'id':'warm','kind':'click','node':'1','label':'Green','role':'button'}]}
        l = await laya_decide(page, 'Click Green.', [])
        return {'qwen_seconds':timing['seconds'],'qwen_response':q,'laya_response':l}
    console.print('Warming local models before task timing...')
    values = asyncio.run(warm())
    record.write_text(json.dumps({'model_process_marker':marker,'purpose':'Synthetic startup warmup, excluded from task timing and acceptance evidence', **values},indent=2))


def call(client, method, path, **kwargs):
    r = client.request(method, path, **kwargs)
    if r.is_error:
        raise RuntimeError(r.text)
    return r.json()


def ensure_service():
    config = settings()
    for name, url in [('service', config['service_url']), ('laya', config['laya_url']),
                      ('qwen', config['qwen_url']), ('whiteboard', BASE)]:
        check_port(name, url)
    from .services import sha256
    manifest = json.loads((ROOT / 'manifest-whiteboard-assets.json').read_text())
    assets = ROOT / 'src/jetson_browser/static/whiteboard'
    for name, expected in manifest['files'].items():
        if sha256(assets / name) != expected:
            raise RuntimeError('Whiteboard asset checksum mismatch: ' + name)
    # Share the model endpoints, but never start/restart the flight service.
    flight = config['service_url']
    if ready(flight):
        h = httpx.get(flight + '/health', trust_env=False, timeout=5).json()
        if h.get('active_tasks'):
            raise RuntimeError('A flight task is active or awaiting input; finish or cancel it first')
    if ready(BASE):
        h = httpx.get(BASE + '/health', trust_env=False, timeout=5).json()
        if h.get('service') != 'jetson-whiteboard':
            raise RuntimeError('Port 8793 is occupied by another service; it was not stopped')
        if h.get('active_tasks'):
            raise RuntimeError('A whiteboard task is active; use whiteboard resume or cancel')
    else:
        # A listener returning a non-health response must not be mistaken for an
        # absent service, and an unrelated process must never be terminated.
        import socket
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', 8793)) == 0:
                raise RuntimeError('Port 8793 is occupied; the existing process was not stopped')
    for name in ('laya', 'qwen'):
        if not ready(config[name + '_url']):
            console.print(f'Loading local {name} model...')
            start_model(name)
            wait_model(name)
    warm_models()
    if not ready(BASE):
        spawn('whiteboard', [sys.executable, '-m', 'uvicorn', 'jetson_browser.whiteboard_service:app',
                            '--host', '127.0.0.1', '--port', '8793'])
        deadline = time.monotonic() + 30
        while not ready(BASE):
            if time.monotonic() >= deadline:
                raise RuntimeError('Whiteboard service did not start; see logs/whiteboard.log')
            time.sleep(.2)


def display(d):
    console.print(f'\nStatus: {d["status"]} — {d["message"]}', markup=False)
    console.print(f'Task elapsed time (excluding model loading): {d["total_seconds"]:.1f}s')
    console.print(f'Laya: {d.get("laya_calls",0)} calls / {d.get("laya_decision_seconds",0):.1f}s | '
        f'Qwen parsing: {d.get("task_parse_seconds",0):.1f}s | Recovery: {d.get("qwen_recovery_seconds",0):.1f}s')
    console.print(f'Logical UI operations: {d["browser_actions"]} | UI input operations: {d.get("ui_actions",0)} | '
        f'UI: {d.get("ui_seconds",0):.1f}s | Wait: {d.get("wait_seconds",0):.1f}s | '
        f'Verification: {d.get("verification_seconds",0):.1f}s | Save: {d.get("save_seconds",0):.1f}s')
    console.print(f'Canvas verified: {d.get("scene_verified",False)} | Human waiting: {d.get("human_wait_seconds",0):.1f}s')
    if d.get('memory'):
        m = d['memory']
        console.print(f'System memory peak: {m["peak_system_used_kib"]/1048576:.2f} GiB | '
            f'Swap peak: {m["peak_swap_used_kib"]/1024:.0f} MiB (0.5s system-wide samples; shared CPU/GPU memory)')
    console.print('Run records: ' + d['run_directory'], markup=False)
    for name, path in d.get('artifacts', {}).items():
        console.print(f'{name}: {path}', markup=False)


def monitor(c, run):
    cursor = 0
    context = Live('', console=console, refresh_per_second=2, transient=True) if console.is_terminal else nullcontext(None)
    try:
        with context as live:
            while True:
                d = call(c, 'GET', '/tasks/' + run)
                if live:
                    live.update(Text(f'Elapsed: {d["total_seconds"]:.1f}s | {d.get("phase","Running")} | {d["browser_actions"]} operations'))
                batch = call(c, 'GET', f'/tasks/{run}/events', params={'after': cursor})
                cursor = batch['next_cursor']
                for e in batch['events']:
                    if e['actor'] in ('executor', 'qwen_parse', 'failure', 'ui_error', 'service', 'executor_guard') and e.get('event_type') != 'operation':
                        console.print(e['message'], markup=False)
                if d['status'] == 'NEEDS_USER':
                    if live:
                        live.stop()
                    text = console.input('Needs user — provide clarification (Ctrl+C to cancel): ')
                    call(c, 'POST', f'/tasks/{run}/resume', json={'additional_information': text})
                    if live:
                        live.start(refresh=True)
                elif d['status'] != 'RUNNING':
                    return d
                time.sleep(.5)
    except (KeyboardInterrupt, EOFError):
        console.print('\nCancelling the task and releasing mouse buttons...')
        return call(c, 'POST', f'/tasks/{run}/cancel', timeout=40)


def main(argv=None):
    p = argparse.ArgumentParser(description='Local-model UI whiteboard assistant')
    sub = p.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run', help='Preload models, then accept English tasks on the same canvas')
    run.add_argument('request', nargs='?')
    run.add_argument('--open', dest='open_file', help='Explicitly open an existing .excalidraw file before accepting tasks')
    for cmd in ('resume', 'cancel'):
        sub.add_parser(cmd).add_argument('run_id')
    sub.add_parser('stop', help='Stop only the whiteboard service/browser; retain shared models and flight assistant')
    args = p.parse_args(argv)
    try:
        if args.command == 'stop':
            stop('whiteboard')
            console.print('Whiteboard stopped. Shared models and flight assistant remain available.')
            return
        if args.command == 'run':
            ensure_service()
        with httpx.Client(base_url=BASE, trust_env=False, timeout=45) as c:
            if args.command in ('resume', 'cancel'):
                if args.command == 'cancel':
                    display(call(c, 'POST', f'/tasks/{args.run_id}/cancel'))
                else:
                    display(monitor(c, args.run_id))
                return
            if args.open_file:
                call(c, 'POST', '/open', json={'path': str(Path(args.open_file).expanduser().resolve())})
                console.print('Scene opened through the file input.')
            try:
                import readline
                readline.set_auto_history(False)
            except ImportError:
                readline = None
            seed = args.request
            while True:
                ensure_service()
                console.print('\nModels ready. Enter an English task; the same canvas will be reused.')
                console.print('Timing starts on Enter. Loading and input waiting are excluded. No video is recorded.')
                try:
                    text = seed if seed is not None else console.input('Task> ')
                    started = time.time()
                except (KeyboardInterrupt, EOFError):
                    break
                text = text.strip()
                if text.casefold() in ('exit', 'quit'):
                    break
                if len(text) < 2 or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
                    console.print('Please enter a complete task. Terminal control input was ignored.')
                    continue
                if readline:
                    readline.add_history(text)
                console.print('Task timer started.')
                result = call(c, 'POST', '/tasks', json={'request': text, 'submitted_at': started})
                finished = monitor(c, result['id'])
                display(finished)
                if seed is not None:
                    if finished['status'] != 'SUCCEEDED':
                        raise SystemExit(1)
                    break
                seed = None
        console.print('\nSession ended. Models and whiteboard remain available.')
    except (OSError, ValueError, RuntimeError, httpx.HTTPError) as error:
        console.print('Whiteboard stopped: ' + str(error), markup=False)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
