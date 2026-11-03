"""Developer diagnostic: inspect the real date widget; not a model acceptance run."""
import asyncio
import json
from jetson_browser.browser import Browser
from jetson_browser.config import ROOT


async def main():
    browser = Browser()
    folder = ROOT / 'evidence/calendar-diagnostic'
    folder.mkdir(parents=True, exist_ok=True)
    await browser.start()
    try:
        await browser.navigate('https://www.trip.com/flights/')
        await browser.page.locator('input[aria-label="Departure airport or city"]').first.wait_for(timeout=45000)

        async def action(label, kind='click', value=None):
            obs = await browser.observe(scope='flight_form')
            matches = [a for a in obs.data['actions'] if a['kind'] == kind and a['label'] == label]
            assert len(matches) == 1, (label, matches)
            result = await browser.execute(obs.id, obs.page_id, matches[0], value)
            print(json.dumps({'actor': 'developer_diagnostic', 'action': matches[0], 'result': result}), flush=True)

        await action('One-way')
        for field, city in [('Departure airport or city', 'Shenzhen'), ('Arrival airport or city', 'Shanghai')]:
            await action(field, 'fill', city)
            await browser.page.wait_for_function("city=>[...document.querySelectorAll('[role=button]')].some(e=>e.innerText.includes(city)&&e.innerText.includes('All airports'))", arg=city, timeout=15000)
            observed = await browser.observe(scope='flight_form')
            options = [a for a in observed.data['actions'] if a['kind'] == 'click' and a['label'].startswith(city + ' · All airports')]
            assert len(options) == 1, options
            await action(options[0]['label'])
        before = await browser.observe(scope='flight_form')
        print('BEFORE_DATE', json.dumps(before.data, ensure_ascii=False), flush=True)
        date_actions = [a for a in before.data['actions'] if a['kind'] == 'click' and (a.get('role') == 'textbox' or a['label'] == 'Any date')]
        if len(date_actions) != 1:
            date_actions = [a for a in before.data['actions'] if a['kind'] == 'click' and __import__('re').search(r'(Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s', a['label'])]
        assert len(date_actions) == 1, date_actions
        await action(date_actions[0]['label'])
        obs = await browser.observe()
        (folder / 'observation.json').write_text(json.dumps(obs.data, ensure_ascii=False, indent=2))
        (folder / 'page.html').write_text(await browser.page.content())
        await browser.screenshot(folder / 'page.png')
        print('TEXT', obs.text[-8500:], flush=True)
        print('CONTROLS', json.dumps([a for a in obs.data['actions'] if a.get('role') not in ['link']], ensure_ascii=False), flush=True)
        print('CALENDAR_MARKUP', json.dumps(await browser.page.evaluate('''()=>[...document.querySelectorAll('[class*="calendar"],[class*="Calendar"],[role=dialog]')].filter(e=>e.getBoundingClientRect().width>0).slice(-12).map(e=>({cls:e.className,html:e.outerHTML.slice(0,14000)}))'''), ensure_ascii=False), flush=True)
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        date = datetime.now(ZoneInfo('Asia/Shanghai')).date() + timedelta(days=11)
        prefix = date.strftime('%A, %B ') + str(date.day) + date.strftime(', %Y')
        from jetson_browser.browser import StaleObservation
        for attempt in range(3):
            obs = await browser.observe()
            date_action = next(a for a in obs.data['actions'] if a['kind'] == 'click' and a['label'].startswith(prefix))
            try:
                print('DATE_CLICK', await browser.execute(obs.id, obs.page_id, date_action), flush=True)
                break
            except StaleObservation:
                if attempt == 2:
                    raise
        form = await browser.observe(scope='flight_form')
        print('FORM_AFTER_DATE', json.dumps(form.data, ensure_ascii=False), flush=True)
        search = next(a for a in form.data['actions'] if a['kind'] == 'click' and a['label'] == 'Search')
        print('SEARCH_CLICK', await browser.execute(form.id, form.page_id, search), flush=True)
        try:
            await browser.page.wait_for_function("()=>/\\d{1,2}:\\d{2}/.test(document.body.innerText)||/no flights|no results|verify|access denied/i.test(document.body.innerText)", timeout=60000)
        except Exception as e:
            print('RESULT_WAIT',str(e),flush=True)
        result = await browser.observe()
        (folder / 'results-observation.json').write_text(json.dumps(result.data, ensure_ascii=False, indent=2))
        (folder / 'results-page.html').write_text(await browser.page.content())
        await browser.screenshot(folder / 'results-page.png')
        print('RESULT_URL', browser.page.url, flush=True)
        print('RESULT_TEXT', result.text[:18000], flush=True)
        print('RESULT_ELEMENTS',json.dumps(await browser.page.evaluate('''()=>[...document.querySelectorAll('[data-testid],[class*="flight-item"],[class*="flight-card"],[class*="flight-list"]')].filter(e=>e.getBoundingClientRect().width>0&&/\\d{1,2}:\\d{2}/.test(e.innerText)).slice(-20).map(e=>({tag:e.tagName,cls:e.className,testid:e.getAttribute('data-testid'),text:e.innerText.slice(0,1800),html:e.outerHTML.slice(0,3000)}))'''),ensure_ascii=False),flush=True)
        await browser.page.locator('[data-testid="u-flight-card-1"] [aria-label="Select this flight"]').click(timeout=15000)
        print('DEVELOPER_DIAGNOSTIC_ONLY selected flight for widget inspection',flush=True)
        selected = browser.page.locator('[data-testid="u-flight-card-1"]')
        try:
            await selected.get_by_text('Book',exact=True).first.wait_for(timeout=15000)
        except Exception:
            pass
        print('EXPANDED_TEXT',await selected.inner_text(),flush=True)
        print('EXPANDED_HTML',(await selected.evaluate('e=>e.outerHTML'))[-25000:],flush=True)
        (folder / 'expanded-page.html').write_text(await browser.page.content())
        await browser.screenshot(folder / 'expanded-page.png')
    finally:
        try:
            failure_state = await browser.observe()
            (folder / 'last-observation.json').write_text(json.dumps(failure_state.data, ensure_ascii=False, indent=2))
        except Exception:
            pass
        await browser.close()


asyncio.run(main())
