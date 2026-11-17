#!/usr/bin/env python3
"""Container lifetime, immutable application links and a single interactive session."""
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import threading
import urllib.request

APP = Path('/opt/jetson-browser')
DATA = Path(os.environ.get('JETSON_BROWSER_ROOT', '/data'))
IDENTITY = {'application': 'jetson-browser-assistant', 'layout': 1}


def link(target, source):
    if target.is_symlink() and target.readlink() == source:
        return
    if target.exists() or target.is_symlink():
        raise RuntimeError(f'Refusing to replace an existing application path: {target}')
    target.symlink_to(source, target_is_directory=source.is_dir())


def prepare():
    marker = DATA / '.jetson-browser-container.json'
    DATA.mkdir(parents=True, exist_ok=True)
    if marker.exists():
        if json.loads(marker.read_text()) != IDENTITY:
            raise RuntimeError('Data directory belongs to another application/layout')
    elif any(DATA.iterdir()):
        raise RuntimeError('Use a new empty data directory; existing projects are never adopted')
    else:
        marker.write_text(json.dumps(IDENTITY) + '\n')
    for name in ('runtime', 'logs', 'evidence', 'runs', 'whiteboard-runs', 'profile', 'home', 'cache', 'xdg'):
        (DATA / name).mkdir(exist_ok=True, mode=0o700)
    (DATA / 'xdg').chmod(0o700)
    for name in ('.venv', 'models', 'src', 'scripts', 'examples', 'config.json', 'artifacts.lock.json',
                 'manifest-laya-browser.json', 'manifest-Qwen3.5-4B-MTP-GGUF.json', 'manifest-whiteboard-assets.json'):
        link(DATA / name, APP / name)
    link(DATA / 'runtime/llama.cpp', APP / 'runtime/llama.cpp')
    link(DATA / 'runtime/llama-commit.txt', APP / 'runtime/llama-commit.txt')


def health():
    for port in (8790, 8791, 8792):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/health', timeout=1) as response:
            if response.status != 200:
                raise RuntimeError(f'Service {port} is not ready')


def session(scene):
    lock = (DATA / 'runtime/session.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('Another terminal session is open. Exit its Task> prompt before switching scenes.') from None
    from jetson_browser.services import service_status
    if any(s.get('active_tasks') for s in service_status()):
        raise RuntimeError('Finish, resume or cancel the active task before opening a new session.')
    os.set_inheritable(lock.fileno(), True)
    args = ['jetson-browser', 'whiteboard', 'run'] if scene == 'whiteboard' else [
        'jetson-browser', 'run', '--loop', '--keep-open', '--no-video', '--visualize']
    os.execvp(args[0], args)


def serve():
    prepare()
    lock = (DATA / 'runtime/container.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    # PIDs from another container are never evidence of ownership in this PID namespace.
    for record in (DATA / 'runtime').glob('*.process.json'):
        record.unlink()
    from jetson_browser.cli import ensure_services
    from jetson_browser.services import stop
    done = threading.Event()
    def terminate(signum, frame):
        raise SystemExit(0)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, terminate)
    try:
        ensure_services()
        print('Container ready. Open a flight or whiteboard session through reComputer.', flush=True)
        while not done.wait(5):
            health()
    finally:
        for name in ('visualizer', 'whiteboard', 'service', 'qwen', 'laya'):
            try:
                stop(name)
            except Exception as error:
                print(f'Cleanup {name}: {error}', file=sys.stderr, flush=True)


def main():
    os.chdir(DATA)
    command = sys.argv[1] if len(sys.argv) > 1 else 'serve'
    if command == 'health':
        health()
    elif command == 'serve':
        serve()
    elif command in ('flights', 'whiteboard'):
        session(command)
    else:
        raise RuntimeError('Expected serve, health, flights or whiteboard')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr, flush=True)
        sys.exit(1)
