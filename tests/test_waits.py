"""Local browser regressions; real-site performance is measured separately."""
import asyncio
from datetime import date
import time

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from jetson_browser.browser import Browser, StaleObservation
from jetson_browser.models import FlightTask
from jetson_browser.trip import Blocked, Trip


@pytest_asyncio.fixture
async def local_browser():
    async with async_playwright() as pw:
        process = await pw.chromium.launch(headless=True, executable_path=pw.chromium.executable_path)
        context = await process.new_context()
        page = await context.new_page()
        browser = Browser()
        browser.page, browser.context = page, context
        try:
            yield browser
        finally:
            await context.close()
            await process.close()


@pytest.mark.asyncio
async def test_removed_control_is_progress_without_waiting_for_old_locator(local_browser):
    b = local_browser
    await b.page.set_content('<button onclick="this.remove()">Remove city</button>')
    obs = await b.observe()
    action = next(a for a in obs.data['actions'] if a['label'] == 'Remove city')
    result = await b.execute(obs.id, obs.page_id, action)
    assert result['page_changed'] and result['progress_reason'] == 'target_removed'
    assert not result['wait_timed_out'] and result['postcondition_wait_seconds'] < 1


@pytest.mark.asyncio
async def test_checked_state_change_is_progress_even_when_page_text_does_not_change(local_browser):
    b = local_browser
    await b.page.set_content('<button role="checkbox" aria-checked="false" onclick="this.setAttribute(\'aria-checked\',\'true\')">Nonstop</button>')
    obs = await b.observe()
    action = next(a for a in obs.data['actions'] if a['label'] == 'Nonstop')
    result = await b.execute(obs.id, obs.page_id, action)
    assert result['progress_reason'] == 'target_state_changed'
    assert result['postcondition_wait_seconds'] < 1


CARD = '''<div data-testid="u-flight-card-1"><span data-testid="flights-name">Test Air</span>
<div aria-label="Flight departing from Shenzhen Bao'an International Airport at 2026-11-13 06:40:00 and arriving at Shanghai Pudong International Airport at 2026-11-13 09:00:00. This is a nonstop flight"></div>
<div aria-label="One-way price: US$126"></div><p>06:40 SZX Nonstop 09:00 PVG US$126</p>
<button aria-label="Select this flight" onclick="document.body.dataset.clicked='yes'">Select</button></div>'''


async def result_page(page):
    await page.route('http://127.0.0.1/**', lambda route: route.fulfill(content_type='text/html', body='''
    <div>1 adult Economy</div><div data-testid="loading-bar" style="width:100px;height:2px">Loading</div>
    <div id="results"></div>'''))
    await page.goto('http://127.0.0.1/results?ddate=2026-11-13&triptype=ow&quantity=1&class=y')
    trip = Trip(FlightTask(origin='Shenzhen', destination='Shanghai', date_text='2026-11-13',
                          departure_date=date(2026, 11, 13), original_request='test', created_at='test'))
    trip.query_proof = {'checks': {'conditions': True}}
    return trip


@pytest.mark.asyncio
async def test_readiness_waits_for_complete_cards_and_ignores_persistent_global_spinner(local_browser):
    b = local_browser
    trip = await result_page(b.page)
    async def insert():
        await asyncio.sleep(.25)
        await b.page.locator('#results').evaluate('(e,html)=>e.innerHTML=html', CARD)
    writer = asyncio.create_task(insert())
    started = time.monotonic()
    result = await trip.wait_for_results(b.page, timeout=3)
    await writer
    assert result['kind'] == 'ready' and len(result['cards']) == 1
    assert .6 < time.monotonic() - started < 2.5
    assert await b.page.locator('[data-testid=loading-bar]').is_visible()


@pytest.mark.asyncio
async def test_incomplete_price_does_not_pass_readiness(local_browser):
    b = local_browser
    trip = await result_page(b.page)
    await b.page.locator('#results').evaluate('(e,html)=>e.innerHTML=html', CARD.replace('One-way price: US$126', 'One-way price: pending'))
    with pytest.raises(Blocked, match='complete, stable'):
        await trip.wait_for_results(b.page, timeout=.7)


@pytest.mark.asyncio
async def test_transient_no_results_does_not_override_verified_cards(local_browser):
    b = local_browser
    trip = await result_page(b.page)
    await b.page.locator('#results').evaluate('(e,html)=>e.innerHTML="<p>No flights found</p>"+html', CARD)
    assert (await trip.wait_for_results(b.page, timeout=2))['kind'] == 'ready'


@pytest.mark.asyncio
async def test_flight_price_change_rejects_old_selection_before_click(local_browser):
    b = local_browser
    trip = await result_page(b.page)
    await b.page.locator('#results').evaluate('(e,html)=>e.innerHTML=html', CARD)
    selected = (await trip.cards(b.page))[0]
    obs = await b.observe(scope='card:' + selected['card_id'])
    action = next(a for a in obs.data['actions'] if a['label'] == 'Select this flight')
    await b.page.locator('[aria-label^="One-way price:"]').evaluate('e=>e.setAttribute("aria-label","One-way price: US$199")')
    assert not await trip.matches_card(b.page, selected)
    with pytest.raises(StaleObservation, match='Flight identity or price changed'):
        await b.execute(obs.id, obs.page_id, action)
    assert await b.page.locator('body').get_attribute('data-clicked') is None


@pytest.mark.asyncio
async def test_scroll_is_progress_without_changing_page_text(local_browser):
    b = local_browser
    await b.page.set_content('<div style="height:4000px">Long page</div>')
    obs = await b.observe()
    action = next(a for a in obs.data['actions'] if a['id'] == 'scroll_down')
    result = await b.execute(obs.id, obs.page_id, action)
    assert result['page_changed'] and result['progress_reason'] == 'scroll_changed'
    assert result['postcondition_wait_seconds'] < 1


def test_typed_city_requires_a_real_matching_suggestion():
    from types import SimpleNamespace
    trip = Trip(FlightTask(origin='Guangzhou', destination='Beijing', date_text='2026-11-20',
                          departure_date=date(2026, 11, 20), original_request='test', created_at='test'))
    checks = {'origin': False, 'destination': False}
    field = {'kind': 'fill', 'role': 'combobox', 'field_label': 'Departure airport or city', 'expanded': 'true', 'raw_value': 'Guangzhou'}
    obs = SimpleNamespace()
    assert not trip.form_ready(obs, checks, [field])
    option = {'kind': 'click', 'role': 'button', 'label': 'Guangzhou All airports China'}
    assert trip.form_ready(obs, checks, [field, option])


@pytest.mark.asyncio
async def test_empty_action_set_never_sends_an_invalid_recovery_schema(monkeypatch):
    from types import SimpleNamespace
    from jetson_browser.runner import Context
    async def forbidden(*args):
        pytest.fail('No model request should be sent for an empty action set')
    monkeypatch.setattr('jetson_browser.runner.laya_decide', forbidden)
    trace = SimpleNamespace(started=time.monotonic(), state={'browser_actions': 0, 'human_wait_seconds': 0})
    context = Context(SimpleNamespace(trace=trace), None)
    with pytest.raises(Blocked, match='No actions are ready'):
        await context.choose(SimpleNamespace(data={'actions': []}), 'test')
