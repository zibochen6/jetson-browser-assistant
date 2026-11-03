import asyncio
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import httpx
import playwright
from playwright.async_api import async_playwright
import pytest

from jetson_browser import service
from jetson_browser.trace import Trace
from jetson_browser.presentation import desktop_layout


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    monkeypatch.setattr('jetson_browser.trace.ROOT', tmp_path)
    monkeypatch.setattr(service, 'sessions', {})
    trace = Trace('Find flights', True, run_id='20261103-120000-aabbccdd')
    trace.set_status('CANCELLED', 'Cancelled for regression testing')
    return trace


@pytest.mark.asyncio
async def test_archive_reads_are_paginated_read_only_and_survive_service_restart(archive):
    folder = archive.folder
    before = {p.name: p.stat().st_mtime_ns for p in folder.iterdir()}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service.app), base_url='http://test') as client:
        listed = (await client.get('/runs')).json()['runs']
        assert listed[0]['id'] == archive.id
        for _ in range(3):
            assert (await client.get('/tasks/' + archive.id)).json()['status'] == 'CANCELLED'
            batch = (await client.get('/tasks/' + archive.id + '/events?after=1')).json()
            assert len(batch['events']) == 1 and batch['next_cursor'] == 2
        assert (await client.get('/tasks/bad-id/events')).status_code == 404
        assert (await client.get('/runs?limit=101')).status_code == 422
        assert (await client.get('/visualizer')).status_code == 200
        assert (await client.get('/visualizer/visualizer.js')).status_code == 200
        assert (await client.get('/visualizer/config.json')).status_code == 404
    assert before == {p.name: p.stat().st_mtime_ns for p in folder.iterdir()}


@pytest.mark.asyncio
async def test_archive_partial_tail_can_be_retried(archive):
    path = archive.folder / 'events.jsonl'
    with path.open('a') as stream:
        stream.write('{"sequence":2')
    batch = service.events(archive.id, after=2)
    assert batch == {'events': [], 'next_cursor': 2}
    with path.open('a') as stream:
        stream.write(',"message":"complete"}\n')
    assert service.events(archive.id, after=2)['next_cursor'] == 3


@pytest.mark.asyncio
async def test_window_setup_refuses_to_touch_active_task(archive, monkeypatch):
    task = asyncio.create_task(asyncio.sleep(10))
    monkeypatch.setattr(service, 'sessions', {archive.id: SimpleNamespace(trace=archive, worker=task)})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service.app), base_url='http://test') as client:
        response = await client.post('/presentation', json={'enabled': True})
        assert response.status_code == 409
        assert (await client.get('/health')).json()['latest_task_id'] == archive.id
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


def test_operation_end_is_recorded_on_cancel_and_active_stack_is_cleared(archive):
    with pytest.raises(asyncio.CancelledError):
        with archive.operation('calendar', 'site_adapter', 'Select date'):
            with archive.operation('execute', 'site_adapter', 'Click date'):
                raise asyncio.CancelledError
    assert archive.state['active_operations'] == []
    operations = [e for e in archive.events if e.get('event_type') == 'operation']
    assert [e['transition'] for e in operations] == ['start', 'start', 'end', 'end']
    assert all(e['outcome'] == 'interrupted' for e in operations[2:])
    assert operations[0]['operation_id'] == operations[-1]['operation_id']
    assert operations[1]['operation_id'] == operations[2]['operation_id']


def test_layout_uses_work_area_without_changing_resolution(monkeypatch):
    def read(args, **kwargs):
        return 'Screen 0: current 3840 x 2160' if args[0] == 'xrandr' else '_NET_WORKAREA(CARDINAL) = 0, 32, 3840, 2128'
    monkeypatch.setattr('jetson_browser.presentation.subprocess.check_output', read)
    layout = desktop_layout()
    assert layout['site'] == {'left': 0, 'top': 32, 'width': 2304, 'height': 2128}
    assert layout['flow'] == {'left': 2304, 'top': 32, 'width': 1536, 'height': 2128}


def test_javascript_projection_preserves_time_attribution_and_terminal_status():
    node = shutil.which('node') or str(Path(playwright.__file__).parent / 'driver' / 'node')
    subprocess.run([node, str(Path(__file__).with_name('visualizer-projection.cjs'))], check=True)


@pytest.mark.asyncio
async def test_actual_flow_page_follows_two_tasks_replays_and_freezes_on_disconnect():
    """UI-only fixtures; real-site acceptance runs are recorded separately on the Jetson."""
    root = Path(service.__file__).parent / 'static'
    first, second = '20261103-120000-aabbccdd', '20261103-120100-aabbccdd'
    clock = {'id': first, 'online': True}
    result = {'id': first, 'status': 'SUCCEEDED', 'request': 'Find flights', 'total_seconds': 10,
              'submitted_at': 1000, 'finished_at': 1010, 'browser_actions': 2, 'query_completed': True,
              'booking_options_opened': True, 'message': 'Fare options verified'}
    events = [
        {'sequence': 0, 'actor': 'qwen_parser', 'message': 'Parse request', 'elapsed_seconds': .1,
         'event_type': 'operation', 'operation_id': 'parse', 'stage': 'parse', 'transition': 'start'},
        {'sequence': 1, 'actor': 'qwen_parser', 'message': 'Parse request', 'elapsed_seconds': 2,
         'event_type': 'operation', 'operation_id': 'parse', 'stage': 'parse', 'transition': 'end', 'duration_seconds': 2},
        {'sequence': 2, 'actor': 'laya', 'message': 'Choose action', 'elapsed_seconds': 3,
         'event_type': 'operation', 'operation_id': 'decide', 'stage': 'decide', 'transition': 'start',
         'candidates': [{'id': 'n1', 'kind': 'click', 'label': '<b>Search</b>'}]},
        {'sequence': 3, 'actor': 'laya', 'message': 'Choose action', 'elapsed_seconds': 4,
         'event_type': 'operation', 'operation_id': 'decide', 'stage': 'decide', 'transition': 'end', 'duration_seconds': 1,
         'selected_action': {'id': 'n1', 'label': '<b>Search</b>'}},
        {'sequence': 4, 'actor': 'service', 'message': 'Fare options verified', 'elapsed_seconds': 10, 'status': 'SUCCEEDED'}]
    async def route(req):
        path = req.request.url.split('8790', 1)[1]
        if path == '/visualizer':
            await req.fulfill(content_type='text/html', body=(root / 'visualizer.html').read_text())
        elif path.startswith('/visualizer/'):
            name = path.rsplit('/', 1)[1]
            await req.fulfill(content_type='text/css' if name.endswith('.css') else 'text/javascript', body=(root / name).read_text())
        elif path == '/health':
            await req.fulfill(status=200 if clock['online'] else 503, json={'active_tasks': [], 'latest_task_id': clock['id']})
        elif path.startswith('/runs'):
            await req.fulfill(json={'runs': [{'id': id, 'status': 'SUCCEEDED'} for id in [clock['id'], first]]})
        elif '/events?' in path:
            after = int(path.rsplit('=', 1)[1]);batch=events[after:]
            await req.fulfill(json={'events': batch, 'next_cursor': after + len(batch)})
        else:
            await req.fulfill(json={**result, 'id': clock['id']})
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, executable_path=pw.chromium.executable_path)
        page = await browser.new_page(viewport={'width': 900, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.route('http://127.0.0.1:8790/**', route)
        try:
            await page.goto('http://127.0.0.1:8790/visualizer')
            await page.wait_for_function("document.querySelector('#status').textContent==='Succeeded'")
            assert await page.locator('#elapsed').inner_text() == '10.0s'
            assert await page.locator('#selection').inner_text() == 'Laya selected: <b>Search</b>'
            assert not await page.locator('#selection b').count()
            clock['id'] = second
            await page.wait_for_function("document.querySelector('#run-id').textContent.includes('120100')")
            await page.locator('#replay').click()
            assert await page.locator('#current-message').inner_text() == 'No event at this replay position'
            await page.locator('#timeline').evaluate("e=>{e.value=.5;e.dispatchEvent(new Event('input'))}")
            assert 'active' in await page.locator('[data-stage=parse]').get_attribute('class')
            assert await page.locator('#query-proof').inner_text() == 'Query: Not verified'
            await page.locator('#speed').select_option('2')
            await page.locator('#play').click()
            await page.wait_for_timeout(300)
            await page.locator('#play').click()
            position = await page.locator('#timeline').input_value()
            await page.wait_for_timeout(250)
            assert await page.locator('#timeline').input_value() == position
            await page.locator('#follow').click()
            clock['online'] = False
            await page.wait_for_function("document.querySelector('#connection').textContent==='Disconnected'")
            frozen = await page.locator('#elapsed').inner_text()
            await page.wait_for_timeout(300)
            assert await page.locator('#elapsed').inner_text() == frozen
            assert not errors
        finally:
            await browser.close()
