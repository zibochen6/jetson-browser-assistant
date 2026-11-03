from datetime import date

import pytest
from playwright.async_api import async_playwright

from jetson_browser.models import FlightTask
from jetson_browser.trip import Trip


@pytest.mark.asyncio
async def test_fare_verifier_waits_for_delayed_itinerary_header():
    trip = Trip(FlightTask(origin='深圳', destination='上海', date_text='2026-11-13',
                          departure_date=date(2026, 11, 13), original_request='test', created_at='test'))
    selected = {'price': 126.0, 'departure_time': '06:40', 'arrival_time': '09:00', 'departure_date': '2026-11-13'}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path=playwright.chromium.executable_path)
        page = await browser.new_page()
        try:
            await page.route('http://127.0.0.1/**', lambda route: route.fulfill(content_type='text/html', body='''
                <div><button aria-label="Close">×</button><div>ShenzhenShanghai</div><div id="itinerary"></div>
                <h2>Select Fare</h2><p>US$126</p><p>Cancellation fee: from US$73</p></div>
                <script>setTimeout(()=>document.getElementById('itinerary').textContent='06:40 – 09:00',500)</script>
            '''))
            await page.goto('http://127.0.0.1/fare?ddate=2026-11-13&midpolicyid=local-test')
            assert await trip._fare_options_once(page, selected) is None
            proof = await trip.fare_options(page, selected)
            assert proof['times_verified'] and proof['date_verified'] and proof['route_verified']
            assert proof['verification_wait_seconds'] > .1
        finally:
            await browser.close()
