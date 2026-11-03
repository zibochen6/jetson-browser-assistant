"""Manage only this project's persistent, loopback-only processes."""
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

import httpx

from .config import ROOT, settings


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def verified_model(name):
    manifest = json.loads((ROOT / f'manifest-{name}.json').read_text())
    entry_name = 'model.safetensors' if name == 'laya-browser' else 'Qwen3.5-4B-Q4_K_M.gguf'
    entry = next(f for f in manifest['files'] if f['path'] == entry_name)
    path = ROOT / ('models/laya-browser' if name == 'laya-browser' else 'models/qwen') / entry_name
    if not path.exists() or path.stat().st_size != entry['bytes']:
        raise RuntimeError(f'Model download/transfer incomplete: {path}')
    digest = sha256(path)
    if digest != entry['sha256']:
        raise RuntimeError(f'Model checksum mismatch: {path}')
    return path, {'repo': manifest['repo'], 'revision': manifest['revision'], 'sha256': digest, 'bytes': path.stat().st_size}


def ready(url):
    try:
        r = httpx.get(url + '/health', timeout=2, trust_env=False)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def owned_pid(name):
    """A PID alone is insufficient: the command and working directory must match."""
    record = ROOT / 'runtime' / (name + '.process.json')
    try:
        data = json.loads(record.read_text())
        proc = Path('/proc') / str(data['pid'])
        command = (proc / 'cmdline').read_bytes().decode(errors='replace')
        if data['marker'] not in command or (proc / 'cwd').resolve() != ROOT.resolve():
            return None
        if data.get('project_root', str(ROOT)) != str(ROOT):
            return None
        return data['pid']
    except (OSError, ValueError, KeyError):
        return None


def check_port(name, url):
    """Refuse unrelated listeners, including another checkout's model service."""
    port = urlparse(url).port
    with socket.socket() as probe:
        probe.settimeout(.3)
        listening = probe.connect_ex(('127.0.0.1', port)) == 0
    if listening and owned_pid(name) is None:
        raise RuntimeError(f'Port {port} is occupied by a process not owned by this checkout. '
                           'Stop the other checkout explicitly or use its launcher; no process was stopped.')


def spawn(name, args):
    (ROOT / 'runtime').mkdir(exist_ok=True)
    (ROOT / 'logs').mkdir(exist_ok=True)
    record = ROOT / 'runtime' / (name + '.process.json')
    if record.exists():
        old = json.loads(record.read_text())
        if owned_pid(name) is not None:
            if old['args'] != args:
                raise RuntimeError(f'{name} already runs with different arguments; stop it before changing mode')
            return old['pid']
    env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'TOKENIZERS_PARALLELISM': 'false', 'PYTHONUNBUFFERED': '1'}
    with (ROOT / 'logs' / (name + '.log')).open('a') as log:
        process = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    marker = next((a for a in args if a.startswith('jetson_browser.')), args[0])
    record.write_text(json.dumps({'pid': process.pid, 'marker': marker, 'args': args,
        'project_root': str(ROOT), 'started_at': time.time()}, indent=2))
    return process.pid


def start_model(name, mtp=None):
    config = settings()
    check_port(name, config[name + '_url'])
    if name == 'laya':
        model, provenance = verified_model('laya-browser')
        args = [sys.executable, '-m', 'uvicorn', 'jetson_browser.laya_server:app', '--host', '127.0.0.1', '--port', '8791']
    elif name == 'qwen':
        model, provenance = verified_model('Qwen3.5-4B-MTP-GGUF')
        enabled = config['mtp'] if mtp is None else mtp
        args = [str(ROOT / 'runtime/llama.cpp/build/bin/llama-server'), '-m', str(model),
                '--host', '127.0.0.1', '--port', '8792', '--device', 'CUDA0', '-ngl', '99', '-c', str(config['context_size']),
                '-np', '1', '-fa', 'on', '--jinja', '--chat-template-kwargs', '{"enable_thinking":false}',
                '--spec-type', 'draft-mtp' if enabled else 'none', '--spec-draft-n-max', str(config['draft_depth']), '--metrics']
        provenance['mtp'] = enabled
    else:
        raise ValueError(name)
    pid = spawn(name, args)
    (ROOT / 'evidence').mkdir(exist_ok=True)
    (ROOT / 'evidence' / (name + '-provenance.json')).write_text(json.dumps(provenance, indent=2))
    return pid


def stop(name):
    record = ROOT / 'runtime' / (name + '.process.json')
    if not record.exists():
        return
    data = json.loads(record.read_text())
    proc = Path('/proc') / str(data['pid']) / 'cmdline'
    if proc.exists() and proc.read_bytes():
        if owned_pid(name) is None:
            raise RuntimeError(f'Refusing to stop reused PID {data["pid"]}')
        # Let the service close its Playwright children before terminating them.
        os.kill(data['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 15
        while proc.exists() and proc.read_bytes() and time.monotonic() < deadline:
            time.sleep(0.2)
        if proc.exists() and proc.read_bytes():
            os.killpg(data['pid'], signal.SIGKILL)
    record.unlink(missing_ok=True)


def service_status():
    config = settings()
    result = []
    for name, url in [('service', config['service_url']), ('laya', config['laya_url']),
                      ('qwen', config['qwen_url']), ('whiteboard', 'http://127.0.0.1:8793')]:
        pid = owned_pid(name)
        item = {'service': name, 'url': url, 'pid': pid, 'status': 'STOPPED'}
        try:
            check_port(name, url)
            if ready(url):
                response = httpx.get(url + '/health', timeout=3, trust_env=False)
                item.update(status='READY', active_tasks=response.json().get('active_tasks', []))
            elif pid:
                item['status'] = 'STARTING / UNHEALTHY'
        except RuntimeError:
            item['status'] = 'OCCUPIED BY ANOTHER CHECKOUT / PROCESS'
        except (ValueError, httpx.HTTPError):
            item['status'] = 'UNHEALTHY'
        result.append(item)
    return result


def wait_model(name, timeout=None):
    config = settings()
    deadline = time.monotonic() + (timeout or config['model_startup_timeout_seconds'])
    url = config[name + '_url']
    while not ready(url):
        record = ROOT / 'runtime' / (name + '.process.json')
        if record.exists():
            data = json.loads(record.read_text())
            proc = Path('/proc') / str(data['pid']) / 'cmdline'
            if not proc.exists() or not proc.read_bytes():
                raise RuntimeError(f'{name} exited; inspect logs/{name}.log')
        if time.monotonic() >= deadline:
            raise TimeoutError(f'{name} startup timed out; inspect logs/{name}.log')
        time.sleep(0.5)
