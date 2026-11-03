"""Inspect the pinned component through the actual Jetson Chromium runtime."""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright
from jetson_browser.config import ROOT, desktop_env


async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(ROOT / 'runtime/whiteboard-m0-profile'), headless=False,
            viewport={'width': 1440, 'height': 1000}, env=desktop_env())
        page = context.pages[0]
        page.set_default_timeout(15000)
        errors, external = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('request', lambda r: external.append(r.url) if r.url.startswith('http') and not r.url.startswith('http://127.0.0.1:8793/') else None)
        await page.goto('http://127.0.0.1:8793/whiteboard/')
        await page.wait_for_function('()=>!!window.whiteboard')
        print('READY', flush=True)
        print(await page.locator('body').inner_text(), flush=True)
        print(await page.locator('input,button').evaluate_all('(es)=>es.map(e=>({label:e.getAttribute("aria-label"),testid:e.getAttribute("data-testid")}))'), flush=True)
        await page.get_by_test_id('toolbar-rectangle').locator('..').click()
        await page.mouse.move(500, 300)
        await page.mouse.down()
        await page.mouse.move(700, 420, steps=16)
        await page.mouse.up()
        await page.mouse.dblclick(600, 360)
        await page.keyboard.insert_text('Camera')
        await page.keyboard.press('Escape')
        print(json.dumps({'scene': await page.evaluate('whiteboard.read()'), 'body': await page.locator('body').inner_text(),
            'controls': await page.locator('button,input,textarea').evaluate_all('(es)=>es.map(e=>({tag:e.tagName,label:e.getAttribute("aria-label"),title:e.getAttribute("title"),testid:e.getAttribute("data-testid"),type:e.type,value:e.value}))'),
            'errors': errors, 'external': external}, indent=2))
        await page.screenshot(path=str(ROOT / 'runtime/whiteboard-m0-ui.png'))
        await context.close()


asyncio.run(main())
