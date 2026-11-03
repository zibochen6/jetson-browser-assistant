import asyncio
from types import SimpleNamespace

import pytest

from jetson_browser import service
from jetson_browser.trace import Trace


def test_terminal_duration_does_not_grow_when_record_is_read_again(tmp_path, monkeypatch):
    monkeypatch.setattr('jetson_browser.trace.ROOT', tmp_path)
    clock = [1005.0]
    monkeypatch.setattr('jetson_browser.trace.time.time', lambda: clock[0])
    trace = Trace('test', True, submitted_at=1000)
    clock[0] = 1010
    trace.set_status('SUCCEEDED', 'test complete')
    assert trace.state['total_seconds'] == 10
    clock[0] = 2000
    trace.save()
    assert trace.state['total_seconds'] == 10


@pytest.mark.asyncio
async def test_concurrent_status_reads_never_write_trace_files(tmp_path, monkeypatch):
    monkeypatch.setattr('jetson_browser.trace.ROOT', tmp_path)
    trace = Trace('test', True)
    before = (trace.folder / 'result.json').stat().st_mtime_ns
    monkeypatch.setattr(service, 'sessions', {trace.id: SimpleNamespace(trace=trace)})
    def forbidden():
        raise AssertionError('Reading status must not persist task state')
    monkeypatch.setattr(trace, 'save', forbidden)
    results = await asyncio.gather(*(service.state(trace.id) for _ in range(100)))
    assert all(r['status'] == 'RUNNING' for r in results)
    assert (trace.folder / 'result.json').stat().st_mtime_ns == before
