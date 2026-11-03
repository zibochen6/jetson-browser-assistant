import argparse
from contextlib import nullcontext
import subprocess
import sys
import time

try:
    import readline
except ImportError:
    readline = None

import httpx
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

from .config import ROOT, settings
from .services import check_port, ready, service_status, spawn, start_model, stop, wait_model

console = Console()
if readline is not None:
    readline.set_auto_history(False)
    readline.set_history_length(100)


def ensure_services(require_idle=False):
    config = settings()
    for name, key in [('service', 'service_url'), ('laya', 'laya_url'), ('qwen', 'qwen_url')]:
        check_port(name, config[key])
    if require_idle and ready(config['service_url']):
        health = httpx.get(config['service_url'] + '/health', timeout=5, trust_env=False).json()
        if health['active_tasks']:
            raise RuntimeError('A task is already running or awaiting input: ' + ', '.join(health['active_tasks']))
    timings = {}
    for name in ['laya', 'qwen']:
        if ready(config[name + '_url']):
            timings[name] = 0.0
            continue
        console.print(f'Loading local {name} model...')
        started = time.perf_counter()
        start_model(name)
        wait_model(name)
        timings[name] = time.perf_counter() - started
        console.print(f'{name} ready ({timings[name]:.1f}s)')
    if not ready(config['service_url']):
        started = time.perf_counter()
        spawn('service', [sys.executable, '-m', 'uvicorn', 'jetson_browser.service:app', '--host', '127.0.0.1', '--port', '8790'])
        deadline = time.monotonic() + 30
        while not ready(config['service_url']):
            if time.monotonic() >= deadline:
                raise TimeoutError('Execution service did not start; see logs/service.log')
            time.sleep(.2)
        timings['service'] = time.perf_counter() - started
    return timings


def request(client, method, path, **kwargs):
    response = client.request(method, settings()['service_url'] + path, **kwargs)
    if response.is_error:
        raise RuntimeError(response.text)
    return response.json()


def prepare_run(task_text=None):
    """Preload before accepting the task; capture the Enter that submits it."""
    timings = ensure_services(require_idle=True)
    if task_text is not None:
        return task_text, time.time(), timings
    console.print('Models ready. Enter a task to start timing. Model loading and input waiting are excluded.')
    console.print('Use YYYY-MM-DD dates. Type exit or quit to leave models and browser running.')
    while True:
        text = console.input('Task> ')
        submitted_at = time.time()
        text = text.strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in text) or text in ['^[[A', '^[[B', '^[[C', '^[[D']:
            console.print('Ignored terminal control input. Recall a complete task with Up/Down, or paste the task again.')
            continue
        if text.casefold() in ['exit', 'quit']:
            return None, submitted_at, timings
        if len(text) >= 2:
            if readline is not None:
                last = readline.get_current_history_length()
                if not last or readline.get_history_item(last) != text:
                    readline.add_history(text)
            return text, submitted_at, timings
        console.print('Please enter a complete task.')


def display_result(result):
    console.print(f'\nStatus: {result["status"]} - {result["message"]}', markup=False)
    if result.get('task'):
        task = result['task']
        console.print(f'Query: {task["origin"]} -> {task["destination"]}, {task["departure_date"]}, one-way, {task["adults"]} adult, economy', markup=False)
    if result.get('candidates'):
        table = Table('Flight', 'Departure', 'Arrival', 'Nonstop', 'Price', 'Price basis')
        for flight in result['candidates']:
            arrival = str(flight.get('arrival_time') or 'Unknown')
            if flight.get('arrival_date') and flight.get('arrival_date') != flight.get('departure_date'):
                arrival = flight['arrival_date'] + ' ' + arrival
            table.add_row(str(flight.get('airline') or 'Unknown') + ' ' + str(flight.get('flight_number') or ''),
                          str(flight.get('departure_time') or 'Unknown') + ' ' + str(flight.get('departure_airport') or 'Unknown'),
                          arrival + ' ' + str(flight.get('arrival_airport') or 'Unknown'),
                          {True: 'Yes', False: 'No', None: 'Unknown'}.get(flight.get('nonstop'), 'Unknown'),
                          f'{flight.get("currency") or "Unknown currency"} {flight.get("price") if flight.get("price") is not None else "Unknown"}',
                          str(flight.get('price_note') or 'Unknown'))
        console.print(table)
        console.print('Options are from verified website results. Prices may change.')
    console.print(f'Current page: {result.get("current_url") or "Not opened"}', markup=False)
    console.print(f'Query verified: {result.get("query_completed", False)} | Details opened: {result.get("details_opened", False)} | Fare options opened: {result.get("booking_options_opened", False)}')
    timing_label = 'Task elapsed time (excluding model loading)' if result.get('timing_scope') == 'after_preload' else 'Total elapsed time'
    console.print(f'{timing_label}: {result.get("total_seconds", 0):.1f}s | Browser actions: {result.get("browser_actions", 0)}')
    if 'laya_decision_seconds' in result:
        console.print(f'Laya decisions: {result["laya_decision_seconds"]:.1f}s | Qwen parsing: {result.get("task_parse_seconds", 0):.1f}s | Qwen input text: {result.get("field_generation_seconds", 0):.1f}s | Recovery: {result.get("qwen_recovery_seconds", 0):.1f}s')
    else:
        console.print(f'Action decisions (legacy aggregate): {result.get("model_decision_seconds", 0):.1f}s')
    console.print(f'Page actions: {result.get("page_interaction_seconds", 0):.1f}s | Result readiness: {result.get("results_wait_seconds", 0):.1f}s | Observation: {result.get("observation_seconds", 0):.1f}s')
    console.print(f'Human takeover: {result.get("human_takeover", False)} | Human waiting: {result.get("human_wait_seconds", 0):.1f}s | Site adapters: {", ".join(result.get("site_adapters", [])) or "None"}')
    console.print(f'Run records: {result.get("run_directory", "")}', markup=False)
    if result.get('keep_open'):
        if result.get('browser_open') is True:
            console.print('Browser remains open on the device desktop.')
        elif result.get('browser_open') is False:
            console.print('Browser is closed. It will be reopened when you submit the next task.')
        else:
            console.print('Browser retention was requested; check the device desktop for this legacy record.')


def monitor(client, task_id):
    cursor = 0
    live_context = Live('', console=console, refresh_per_second=2, transient=True) if console.is_terminal else nullcontext(None)
    try:
        with live_context as live:
            while True:
                result = request(client, 'GET', f'/tasks/{task_id}')
                if live:
                    stage = {'parse': 'Parsing request', 'query_conditions': 'Search form', 'results': 'Flight results'}.get(result.get('phase'), 'Running')
                    live.update(Text(f'Elapsed: {result.get("total_seconds", 0):.1f}s | Stage: {stage}'))
                batch = request(client, 'GET', f'/tasks/{task_id}/events', params={'after': cursor})
                cursor = batch['next_cursor']
                for event in batch['events']:
                    if event['actor'] != 'action_preconditions' and event.get('event_type') != 'operation':
                        console.print(event['message'], markup=False)
                if result['status'] == 'NEEDS_USER':
                    if not sys.stdin.isatty():
                        console.print(f'User input required. Resume with: jetson-browser resume {task_id}')
                        return result
                    if live:
                        live.stop()
                    prompt = 'Provide the missing or ambiguous information: ' if result.get('missing') else 'Complete the required step in the browser, then press Enter: '
                    information = console.input(prompt)
                    request(client, 'POST', f'/tasks/{task_id}/resume', json={'additional_information': information})
                    if live:
                        live.start(refresh=True)
                elif result['status'] != 'RUNNING':
                    return result
                time.sleep(.5)
    except (KeyboardInterrupt, EOFError):
        console.print('\nCancelling the current task and saving records...')
        try:
            return request(client, 'POST', f'/tasks/{task_id}/cancel', timeout=30)
        except Exception:
            stop('service')
            raise RuntimeError('Execution service stopped. Inspect the run records before starting another task.')


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'whiteboard':
        from .whiteboard_cli import main as whiteboard_main
        return whiteboard_main(sys.argv[2:])
    parser = argparse.ArgumentParser(description='Local decision-model browser and whiteboard assistant for Jetson Orin NX 16GB')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('whiteboard', help='Local UI whiteboard: run, resume, cancel or stop')
    run = sub.add_parser('run', help='Search real flights and open matching fare options')
    run.add_argument('request', nargs='?', help='Omit to preload models and prompt for a task')
    run.add_argument('--loop', action='store_true', help='Return to Task> after each task')
    run.add_argument('--keep-open', action='store_true', help='Keep the browser open after the task')
    run.add_argument('--site', choices=['trip'], default='trip')
    run.add_argument('--query-only', action='store_true', help='Verify search results without opening fare options')
    run.add_argument('--no-video', action='store_true', help='Disable built-in recording for this task')
    run.add_argument('--visualize', action=argparse.BooleanOptionalAction, default=False,
                     help='Open the read-only live flow and arrange the desktop windows')
    resume = sub.add_parser('resume', help='Resume a task awaiting user input')
    resume.add_argument('task_id')
    cancel = sub.add_parser('cancel', help='Cancel a task and retain records')
    cancel.add_argument('task_id')
    sub.add_parser('doctor', help='Check the environment and real CUDA computation')
    sub.add_parser('status', help='Show model/execution health without loading models or submitting tasks')
    sub.add_parser('start', help='Preload local models and start the execution service')
    sub.add_parser('visualize', help='Open or reuse the live flow without submitting a task')
    sub.add_parser('stop', help='Stop this project\'s services and browser')
    args = parser.parse_args()
    task_id = None
    try:
        if args.command == 'status':
            for item in service_status():
                console.print(f'{item["service"]}: {item["status"]} | {item["url"]} | PID: {item["pid"] or "-"}', markup=False)
                if item.get('active_tasks'):
                    console.print('  Active or awaiting input: ' + ', '.join(item['active_tasks']), markup=False)
            return
        if args.command == 'doctor':
            for name in ['check_env.py', 'gpu_check.py']:
                subprocess.run([sys.executable, str(ROOT / 'scripts' / name)], cwd=ROOT, check=True)
            return
        if args.command == 'stop':
            stop('visualizer')
            stop('service')
            for name in ['qwen', 'laya']:
                stop(name)
            console.print('Project services stopped.')
            return
        if args.command == 'start':
            ensure_services()
            console.print('Local models and execution service are ready.')
            return
        if args.command == 'visualize' or (args.command == 'run' and args.visualize):
            from .presentation import launch_visualizer
            ensure_services(require_idle=True)
            launch_visualizer()
            console.print('Live flow ready. No screen recording is started.')
            if args.command == 'visualize':
                return
        elif args.command == 'run' and '--no-visualize' in sys.argv:
            ensure_services(require_idle=True)
            stop('visualizer')
            response = httpx.post(settings()['service_url'] + '/presentation', json={'enabled': False},
                                  timeout=15, trust_env=False)
            response.raise_for_status()
        with httpx.Client(timeout=40, trust_env=False) as client:
            if args.command in ['cancel', 'resume']:
                if args.command == 'cancel':
                    display_result(request(client, 'POST', f'/tasks/{args.task_id}/cancel'))
                    return
                ensure_services()
                current = request(client, 'GET', f'/tasks/{args.task_id}')
                if current['status'] == 'NEEDS_USER':
                    information = console.input('Provide clarification, or finish the browser step and press Enter: ')
                    request(client, 'POST', f'/tasks/{args.task_id}/resume', json={'additional_information': information})
                result = monitor(client, args.task_id)
                display_result(result)
                if result['status'] not in ['SUCCEEDED', 'NO_RESULTS']:
                    raise SystemExit(3 if result['status'] == 'NEEDS_USER' else 1)
                return
            seed_task = args.request
            while True:
                task_id = None
                try:
                    task_text, started, timings = prepare_run(seed_task)
                except (EOFError, KeyboardInterrupt):
                    task_text = None
                seed_task = None
                if task_text is None:
                    console.print('\nSession ended. Models and browser remain available.')
                    return
                console.print('Task timer started.')
                response = request(client, 'POST', '/tasks', json={'request': task_text, 'keep_open': args.keep_open,
                    'site': args.site, 'open_details': not args.query_only, 'submitted_at': started, 'startup_seconds': timings,
                    'timing_scope': 'after_preload', 'record_video': False if args.no_video else None})
                task_id = response['id']
                result = monitor(client, task_id)
                display_result(result)
                if not args.loop or result['status'] == 'NEEDS_USER':
                    if result['status'] not in ['SUCCEEDED', 'NO_RESULTS']:
                        raise SystemExit(3 if result['status'] == 'NEEDS_USER' else 1)
                    return
    except (RuntimeError, ValueError, TimeoutError, OSError, subprocess.CalledProcessError, httpx.HTTPError) as error:
        console.print(f'Execution stopped: {error}', markup=False)
        if task_id:
            console.print(f'Task may still exist. Inspect or resume it with: jetson-browser resume {task_id}')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
