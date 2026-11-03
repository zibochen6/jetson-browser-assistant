import pytest
from jetson_browser.browser import Browser, Observation, StaleObservation


@pytest.mark.asyncio
async def test_stale_observation_rejected_before_touching_browser():
    browser = Browser()
    browser.last = Observation('new', 'page-a', 'https://www.trip.com/flights/', {'actions': []}, '')
    with pytest.raises(StaleObservation):
        await browser.execute('old', 'page-a', {'id': 'n1_click', 'kind': 'click'})
