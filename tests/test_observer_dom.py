"""Local structural regression only; this never replaces real Trip.com acceptance."""
import pytest
from playwright.async_api import async_playwright

from jetson_browser.browser import CONTROLS_JS


@pytest.mark.asyncio
async def test_portal_suggestions_and_chip_removal_keep_field_identity():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, executable_path=playwright.chromium.executable_path)
        page = await browser.new_page()
        try:
            await page.set_content('''
            <style>input{width:180px;height:30px} [tabindex]{cursor:pointer}
            .field{display:inline-block} .popup{position:absolute;top:200px;left:250px}</style>
            <section><div role="radio" aria-checked="true">One-way</div><div>
              <div class="field"><input role="combobox" aria-label="Departure airport or city" aria-expanded="false"></div>
              <div class="field"><input role="combobox" aria-label="Arrival airport or city" aria-expanded="false"></div>
              <button>Search</button></div></section>
            <div class="popup"><div><span>Shanghai<i role="button" aria-label="Remove">×</i></span>
              <input role="combobox" aria-label="Arrival airport or city" aria-expanded="true" value="Beijing"></div>
              <div role="button">Beijing · All airports</div>
              <div role="listitem" tabindex="0"><span>PEK Beijing Capital International Airport</span><span>26 km from city center</span></div>
            </div>''')
            observation = await page.evaluate(CONTROLS_JS, 'flight_form')
            actions = observation['actions']
            suggestion = next(a for a in actions if a['label'] == 'Beijing · All airports')
            assert suggestion['field_label'] == 'Arrival airport or city'
            remove = next(a for a in actions if a.get('dom_label') == 'Remove')
            assert remove['field_label'] == 'Arrival airport or city'
            assert 'Shanghai' in remove['label']
            airport = [a for a in actions if 'PEK' in a['label']]
            assert len(airport) == 1  # Full airport row; no duplicate inherited pointer spans.
            assert airport[0]['role'] == 'listitem'
        finally:
            await browser.close()
