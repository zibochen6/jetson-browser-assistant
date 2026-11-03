"""Reopen an already observed URL for widget inspection; never an acceptance run."""
import asyncio
import json
from jetson_browser.browser import Browser
from jetson_browser.config import ROOT


async def main():
    url = json.loads((ROOT / 'evidence/calendar-diagnostic/results-observation.json').read_text())['url']
    b = Browser()
    await b.start()
    try:
        await b.navigate(url)
        card = b.page.locator('[data-testid="u-flight-card-1"]')
        await card.wait_for(state='attached', timeout=60000)
        await card.locator('[aria-label="Select this flight"]').click(timeout=15000)
        if len(b.context.pages) > 1:
            b.page = b.context.pages[-1]
            await b.page.wait_for_load_state('domcontentloaded',timeout=45000)
            print('NEW_PAGE',b.page.url,flush=True)
        try:
            await card.get_by_text('Book', exact=True).first.wait_for(timeout=15000)
        except Exception:
            pass
        folder = ROOT / 'evidence/details-diagnostic'
        folder.mkdir(exist_ok=True, parents=True)
        (folder / 'card.html').write_text(await card.evaluate('e=>e.outerHTML'))
        (folder / 'page.html').write_text(await b.page.content())
        await b.screenshot(folder / 'page.png')
        print('DIAGNOSTIC_ONLY', url)
        print('TEXT', await card.inner_text())
        print('CONTROLS', json.dumps((await b.observe()).data['actions'], ensure_ascii=False))
        print('ALL_PAGES',[(p.url) for p in b.context.pages],flush=True)
        print('ACTIVE_TEXT',await b.page.locator('body').inner_text(),flush=True)
    finally:
        await b.close()


asyncio.run(main())
