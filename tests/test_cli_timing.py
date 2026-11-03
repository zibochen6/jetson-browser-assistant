import sys
from unittest.mock import MagicMock

import pytest

from jetson_browser import cli
from jetson_browser.trace import Trace


@pytest.mark.parametrize('interactive', [True, False])
def test_task_clock_starts_after_preload_and_task_entry(tmp_path, monkeypatch, interactive):
    clock = [100.0]
    def load(**kwargs):
        clock[0] += 30
        return {'qwen': 30.0, 'laya': 0.0}
    def read(prompt):
        clock[0] += 20  # Time spent entering the task is not execution time.
        return 'search flights'
    monkeypatch.setattr(cli, 'ensure_services', load)
    monkeypatch.setattr(cli.console, 'input', read)
    monkeypatch.setattr(cli.time, 'time', lambda: clock[0])
    monkeypatch.setattr('jetson_browser.trace.ROOT', tmp_path)
    text, started, startup = cli.prepare_run(None if interactive else 'search flights')
    assert started == (150 if interactive else 130)
    trace = Trace(text, True, submitted_at=started, startup=startup, timing_scope='after_preload')
    clock[0] += 4
    trace.set_status('SUCCEEDED', 'complete')
    assert trace.state['total_seconds'] == 4
    assert trace.state['startup_seconds']['qwen'] == 30


def test_blank_input_does_not_start_a_task_clock(monkeypatch):
    clock = [100.0]
    entries = iter(['', 'search flights'])
    def read(prompt):
        clock[0] += 20
        return next(entries)
    monkeypatch.setattr(cli, 'ensure_services', lambda **kwargs: {})
    monkeypatch.setattr(cli.console, 'input', read)
    monkeypatch.setattr(cli.time, 'time', lambda: clock[0])
    assert cli.prepare_run()[1] == 140


def test_interactive_run_passes_recording_override_and_enter_time(monkeypatch):
    captured = {}
    monkeypatch.setattr(sys, 'argv', ['jetson-browser', 'run', '--keep-open', '--no-video'])
    monkeypatch.setattr(cli, 'prepare_run', lambda text: ('search flights', 123.0, {'qwen': 30.0}))
    monkeypatch.setattr(cli.httpx, 'Client', lambda **kwargs: MagicMock())
    def submit(client, method, path, **kwargs):
        captured.update(kwargs['json'])
        return {'id': 'test'}
    monkeypatch.setattr(cli, 'request', submit)
    monkeypatch.setattr(cli, 'monitor', lambda *args: {'status': 'SUCCEEDED'})
    monkeypatch.setattr(cli, 'display_result', lambda result: None)
    cli.main()
    assert captured['submitted_at'] == 123.0
    assert captured['timing_scope'] == 'after_preload'
    assert captured['record_video'] is False
    assert captured['keep_open'] is True
