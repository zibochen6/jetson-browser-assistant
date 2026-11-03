import io
import re
import sys
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from jetson_browser import cli


@pytest.mark.parametrize('first_status', ['SUCCEEDED', 'FAILED', 'BLOCKED', 'CANCELLED'])
def test_loop_returns_to_prompt_and_timestamps_each_task_independently(monkeypatch, first_status):
    entries = iter([('first task', 100, {}), ('second task', 200, {}), (None, 300, {})])
    results = iter([{'status': first_status}, {'status': 'SUCCEEDED'}])
    submitted, displayed = [], []
    monkeypatch.setattr(sys, 'argv', ['jetson-browser', 'run', '--loop', '--keep-open', '--no-video'])
    monkeypatch.setattr(cli, 'prepare_run', lambda text: next(entries))
    monkeypatch.setattr(cli.httpx, 'Client', lambda **kwargs: MagicMock())
    def send(client, method, path, **kwargs):
        submitted.append(kwargs['json'])
        return {'id': str(len(submitted))}
    monkeypatch.setattr(cli, 'request', send)
    monkeypatch.setattr(cli, 'monitor', lambda *args: next(results))
    monkeypatch.setattr(cli, 'display_result', displayed.append)
    cli.main()
    assert [s['submitted_at'] for s in submitted] == [100, 200]
    assert all(s['record_video'] is False and s['keep_open'] for s in submitted)
    assert len(displayed) == 2


@pytest.mark.parametrize('text', ['quit', 'exit', 'EXIT'])
def test_quit_does_not_submit_a_task(monkeypatch, text):
    monkeypatch.setattr(cli, 'ensure_services', lambda **kwargs: {})
    monkeypatch.setattr(cli.console, 'input', lambda prompt: text)
    assert cli.prepare_run()[0] is None


def test_english_output_and_frozen_timing_label(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(cli, 'console', Console(file=out, width=160, color_system=None))
    cli.display_result({'status': 'SUCCEEDED', 'message': 'Fare options verified', 'timing_scope': 'after_preload',
                        'total_seconds': 12.5, 'laya_decision_seconds': 3, 'keep_open': True})
    text = out.getvalue()
    assert 'Task elapsed time (excluding model loading): 12.5s' in text
    assert 'Laya decisions: 3.0s' in text
    assert not re.search(r'[\u4e00-\u9fff]', text)


def test_ctrl_c_cancels_task_and_retains_models(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, 'console', Console(file=io.StringIO()))
    def send(client, method, path, **kwargs):
        calls.append((method, path))
        if path.endswith('/cancel'):
            return {'status': 'CANCELLED'}
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, 'request', send)
    monkeypatch.setattr(cli, 'stop', lambda name: pytest.fail('Models or service should not stop after successful cancellation'))
    assert cli.monitor(None, 'example')['status'] == 'CANCELLED'
    assert calls[-1] == ('POST', '/tasks/example/cancel')


def test_ctrl_c_at_idle_prompt_exits_without_submitting(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['jetson-browser', 'run', '--loop'])
    monkeypatch.setattr(cli.httpx, 'Client', lambda **kwargs: MagicMock())
    def interrupted(text):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, 'prepare_run', interrupted)
    monkeypatch.setattr(cli, 'request', lambda *args, **kwargs: pytest.fail('No task should be submitted'))
    cli.main()


@pytest.mark.parametrize('control', ['\x1b[A', '\x1b[B', '^[[A', '^[[B'])
def test_terminal_control_sequences_never_become_tasks(monkeypatch, control):
    entries = iter([control, 'Find flights from Shenzhen'])
    monkeypatch.setattr(cli, 'ensure_services', lambda **kwargs: {})
    monkeypatch.setattr(cli.console, 'input', lambda prompt: next(entries))
    assert cli.prepare_run()[0] == 'Find flights from Shenzhen'


def test_closed_browser_is_not_reported_as_still_open(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(cli, 'console', Console(file=out, width=160, color_system=None))
    cli.display_result({'status': 'BLOCKED', 'message': 'Browser closed', 'keep_open': True, 'browser_open': False})
    assert 'Browser remains open' not in out.getvalue()
    assert 'will be reopened' in out.getvalue()
