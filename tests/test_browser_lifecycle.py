"""Actual Chromium lifecycle regressions, using a private local test profile."""
import pytest
import pytest_asyncio
from playwright.async_api import Error as PlaywrightError

from jetson_browser.browser import Browser, BrowserClosedError, StaleObservation


@pytest_asyncio.fixture
async def browser(tmp_path):
    b = Browser(profile_dir=tmp_path / 'profile', headless=True)
    await b.start()
    try:
        yield b
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_closing_whole_browser_reopens_same_profile_for_next_task(browser):
    b = browser
    old_page = b.page
    old_context = b.context
    await old_context.close()
    assert not b.is_open()
    await b.navigate('data:text/html,<title>Recovered</title><p>New task</p>')
    assert b.is_open() and b.page is not old_page and b.context is not old_context
    assert await b.page.title() == 'Recovered'


@pytest.mark.asyncio
async def test_closed_non_null_context_is_not_reused(browser):
    b = browser
    stale_context, stale_page = b.context, b.page
    await stale_context.close()
    # Reproduce a stale reference even if a close notification was missed.
    b.context, b.page = stale_context, stale_page
    await b.start()
    assert b.is_open() and b.context is not stale_context


@pytest.mark.asyncio
async def test_closing_selected_tab_reuses_another_live_tab(browser):
    b = browser
    context = b.context
    other = await context.new_page()
    await b.page.close()
    await b.start()
    assert b.context is context and b.page is other and b.is_open()


@pytest.mark.asyncio
async def test_navigation_close_race_is_retried_once(browser, monkeypatch):
    b = browser
    old_page = b.page
    async def closed(*args, **kwargs):
        await b.context.close()
        raise PlaywrightError('Target page, context or browser has been closed')
    monkeypatch.setattr(old_page, 'goto', closed)
    await b.navigate('data:text/html,<title>Retry succeeded</title>')
    assert b.page is not old_page and await b.page.title() == 'Retry succeeded'


@pytest.mark.asyncio
async def test_repeated_navigation_close_has_a_bounded_retry(browser, monkeypatch):
    b = browser
    original_start = b.start
    calls = []
    async def closed(*args, **kwargs):
        calls.append('goto')
        raise PlaywrightError('Target page, context or browser has been closed')
    async def start(*args, **kwargs):
        await original_start(*args, **kwargs)
        monkeypatch.setattr(b.page, 'goto', closed)
    monkeypatch.setattr(b, 'start', start)
    with pytest.raises(BrowserClosedError, match='twice during startup'):
        await b.navigate('data:text/html,never reached')
    assert len(calls) == 2 and not b.is_open()


@pytest.mark.asyncio
async def test_closed_browser_does_not_replay_old_actions(browser):
    b = browser
    await b.page.set_content('<button>Search</button>')
    obs = await b.observe()
    action = next(a for a in obs.data['actions'] if a['label'] == 'Search')
    await b.context.close()
    with pytest.raises(BrowserClosedError):
        await b.execute(obs.id, obs.page_id, action)
    assert not b.is_open()
    await b.start()
    with pytest.raises(StaleObservation):
        await b.execute(obs.id, obs.page_id, action)


@pytest.mark.asyncio
async def test_close_clears_all_handles_and_is_idempotent(browser):
    b = browser
    await b.observe()
    await b.close()
    await b.close()
    assert b.context is None and b.page is None and b.pw is None
    assert b.last is None and not b.page_ids
