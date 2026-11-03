"""Installer/provenance checks; these do not replace real Jetson task acceptance."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import deployment


def module(name):
    spec = importlib.util.spec_from_file_location('test_' + name, SCRIPTS / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def server():
    payload = b'PK\x03\x04' + b'controlled test artifact' * 100
    state = {'mode': 'range', 'requests': []}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            state['requests'].append(self.headers.get('Range'))
            if state['mode'] == 'html':
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<html>Access denied</html>')
                return
            offset = int(self.headers.get('Range', 'bytes=0-').split('=')[1].split('-')[0])
            partial = state['mode'] != 'ignore' and self.headers.get('Range')
            data = payload[offset:] if partial else payload
            self.send_response(206 if partial else 200)
            if partial:
                self.send_header('Content-Range', f'bytes {offset if state["mode"] != "bad_range" else 0}-{len(payload)-1}/{len(payload)}')
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}/artifact', payload, state
    finally:
        http.shutdown()
        http.server_close()
        worker.join()


def expected(payload):
    return {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}


@pytest.mark.parametrize('mode', ['range', 'ignore'])
def test_resume_and_ignored_range_are_verified_before_publication(tmp_path, server, mode):
    url, payload, state = server
    state['mode'] = mode
    target = tmp_path / 'path with spaces/wheel.whl'
    target.parent.mkdir()
    partial = target.with_suffix('.whl.partial')
    partial.write_bytes(payload[:17])
    deployment.download(url, target, expected(payload), attempts=1)
    assert target.read_bytes() == payload and not partial.exists()
    assert state['requests'] == ['bytes=17-']
    deployment.download(url, target, expected(payload), offline=True)
    assert len(state['requests']) == 1


@pytest.mark.parametrize('mode', ['html', 'bad_range'])
def test_error_pages_and_wrong_ranges_never_become_artifacts(tmp_path, server, mode):
    url, payload, state = server
    state['mode'] = mode
    target = tmp_path / 'wheel.whl'
    if mode == 'bad_range':
        target.with_suffix('.whl.partial').write_bytes(payload[:17])
    with pytest.raises(RuntimeError):
        deployment.download(url, target, expected(payload), attempts=1)
    assert not target.exists()


def test_checksum_mismatch_preserves_existing_file_and_offline_never_connects(tmp_path, server):
    url, payload, state = server
    target = tmp_path / 'wheel.whl'
    target.write_bytes(b'old data')
    bad = expected(payload)
    bad['sha256'] = '0' * 64
    with pytest.raises(RuntimeError):
        deployment.download(url, target, bad, attempts=1)
    assert target.read_bytes() == b'old data'
    before = list(state['requests'])
    with pytest.raises(RuntimeError, match='Offline'):
        deployment.download(url, target, expected(payload), offline=True)
    assert state['requests'] == before


def test_preflight_rejects_wrong_arch_cuda_and_memory():
    setup = module('setup')
    valid = ('Linux', 'aarch64', '3.10', '# R36 (release), REVISION: 4.3', 'Cuda compilation tools, release 12.6', 16 * 1024 * 1024)
    assert setup.host_errors(*valid) == []
    for index, value in [(0, 'Darwin'), (1, 'x86_64'), (2, '3.12'), (3, 'R35'), (4, 'release 12.2'), (5, 8 * 1024 * 1024)]:
        changed = list(valid)
        changed[index] = value
        assert setup.host_errors(*changed)


def test_release_export_excludes_local_records_and_allows_sources():
    release = module('prepare_release')
    for path in ['evidence/environment.json', 'runtime/qwen.process.json', 'models/model.gguf', '.env', 'config.local.json', 'profile/Cookies', 'whiteboard-runs/id/result.json', 'docs/original-requirements.txt', 'frontend/whiteboard/node_modules/x', '../private']:
        assert not release.public_path(path), path
    for path in ['README.md', 'LICENSE', 'src/jetson_browser/cli.py', 'scripts/setup.py', '.github/workflows/checks.yml', 'docs/usage.md']:
        assert release.public_path(path), path


def test_local_config_is_private_and_rejects_unknown_remote_or_bad_values(tmp_path, monkeypatch):
    from jetson_browser import config
    original = json.loads((config.ROOT / 'config.json').read_text())
    (tmp_path / 'config.json').write_text(json.dumps(original))
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    path = tmp_path / 'config.local.json'
    path.write_text('{"timeout_seconds":120,"record_video":false}')
    assert config.settings()['timeout_seconds'] == 120
    for value in [{'laya_url':'https://example.com'}, {'unexpected':True}, {'max_actions':False}, {'mtp':'true'}, {'timeout_seconds':0}]:
        path.write_text(json.dumps(value))
        with pytest.raises(ValueError):
            config.settings()


def test_desktop_runtime_uses_current_uid_and_preserves_explicit_settings(monkeypatch):
    from jetson_browser.config import desktop_env
    monkeypatch.delenv('XDG_RUNTIME_DIR', raising=False)
    monkeypatch.delenv('XAUTHORITY', raising=False)
    monkeypatch.setattr('jetson_browser.config.os.getuid', lambda: 1234)
    assert desktop_env()['XDG_RUNTIME_DIR'] == '/run/user/1234'
    monkeypatch.setenv('XAUTHORITY', '/my/desktop/authority')
    monkeypatch.setenv('DISPLAY', ':2')
    assert desktop_env()['XAUTHORITY'] == '/my/desktop/authority'
    assert desktop_env()['DISPLAY'] == ':2'


def test_listener_without_ownership_is_not_reused(monkeypatch):
    from jetson_browser import services
    monkeypatch.setattr(services, 'owned_pid', lambda name: None)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        with pytest.raises(RuntimeError, match='not owned'):
            services.check_port('laya', f'http://127.0.0.1:{listener.getsockname()[1]}')


def test_pid_identity_also_requires_the_original_working_directory(tmp_path, monkeypatch):
    from jetson_browser import services
    project = tmp_path / 'project'
    other = tmp_path / 'another checkout'
    project.mkdir(); other.mkdir()
    (project / 'runtime').mkdir()
    (project / 'runtime/laya.process.json').write_text(json.dumps({'pid':123,'marker':'jetson_browser.laya_server','project_root':str(project)}))
    proc = tmp_path / 'proc/123'
    proc.mkdir(parents=True)
    (proc / 'cmdline').write_bytes(b'python\0jetson_browser.laya_server\0')
    (proc / 'cwd').symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(services, 'ROOT', project)
    monkeypatch.setattr(services, 'Path', lambda value: tmp_path / 'proc' if value == '/proc' else Path(value))
    assert services.owned_pid('laya') is None
    (proc / 'cwd').unlink()
    (proc / 'cwd').symlink_to(project, target_is_directory=True)
    assert services.owned_pid('laya') == 123
