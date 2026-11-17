"""Data isolation checks; CUDA and real desktop acceptance run on the Jetson."""
import importlib.util
import json
from pathlib import Path

import pytest


def runtime(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'docker/runtime.py'
    spec = importlib.util.spec_from_file_location('container_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = tmp_path / 'immutable-app'
    app.mkdir()
    (app / 'runtime').mkdir()
    data = tmp_path / 'persistent'
    monkeypatch.setattr(module, 'APP', app)
    monkeypatch.setattr(module, 'DATA', data)
    return module


def test_container_keeps_mutable_state_across_repeated_initialization(tmp_path, monkeypatch):
    module = runtime(tmp_path, monkeypatch)
    module.prepare()
    saved = module.DATA / 'whiteboard-runs' / 'user-scene.json'
    saved.write_text('{"keep":true}')
    module.prepare()
    assert saved.read_text() == '{"keep":true}'
    assert (module.DATA / 'models').readlink() == module.APP / 'models'
    assert (module.DATA / 'runtime/llama.cpp').readlink() == module.APP / 'runtime/llama.cpp'
    assert not (module.APP / 'whiteboard-runs').exists()


def test_container_never_adopts_or_overwrites_a_native_checkout(tmp_path, monkeypatch):
    module = runtime(tmp_path, monkeypatch)
    module.DATA.mkdir()
    original = module.DATA / 'config.json'
    original.write_text('private')
    with pytest.raises(RuntimeError, match='new empty'):
        module.prepare()
    assert original.read_text() == 'private'


def test_container_rejects_conflicting_model_paths_even_with_ownership_marker(tmp_path, monkeypatch):
    module = runtime(tmp_path, monkeypatch)
    module.prepare()
    (module.DATA / 'models').unlink()
    (module.DATA / 'models').mkdir()
    with pytest.raises(RuntimeError, match='Refusing to replace'):
        module.prepare()
