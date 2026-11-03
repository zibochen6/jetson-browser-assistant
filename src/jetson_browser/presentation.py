"""Local desktop layout and a separate, read-only presentation browser."""
import asyncio
import json
import os
import re
import signal
import subprocess
import time

import httpx
from playwright.async_api import async_playwright

from .config import ROOT, desktop_env, settings


def desktop_layout():
    width, height, x, y = 1920, 1048, 0, 32
    try:
        output = subprocess.check_output(['xrandr', '--current'], env=desktop_env(), text=True, timeout=3)
        match = re.search(r'current (\d+) x (\d+)', output)
        if match:
            width, height = map(int, match.groups())
            height = max(500, height - y)
        output = subprocess.check_output(['xprop', '-root', '_NET_WORKAREA'], env=desktop_env(), text=True, timeout=3)
        match = re.search(r'=\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)', output)
        if match:
            x, y, width, height = map(int, match.groups())
    except (OSError, subprocess.SubprocessError):
        pass
    split = int(width * .6)
    return {'site': {'left': x, 'top': y, 'width': split, 'height': height},
            'flow': {'left': x + split, 'top': y, 'width': width - split, 'height': height}}


async def window_bounds(context, page, bounds):
    session = await context.new_cdp_session(page)
    try:
        window = await session.send('Browser.getWindowForTarget')
        await session.send('Browser.setWindowBounds', {'windowId': window['windowId'], 'bounds': {'windowState': 'normal'}})
        await session.send('Browser.setWindowBounds', {'windowId': window['windowId'], 'bounds': bounds})
    finally:
        await session.detach()


def launch_visualizer():
    """Called by the CLI before accepting a task; no model calls are made here."""
    import sys
    from .services import spawn
    url = settings()['service_url']
    response = httpx.post(url + '/presentation', json={'enabled': True}, timeout=40, trust_env=False)
    response.raise_for_status()
    pid = spawn('visualizer', [sys.executable, '-m', 'jetson_browser.presentation'])
    deadline = time.monotonic() + 15
    while True:
        try:
            ready = json.loads((ROOT / 'runtime' / 'visualizer-ready.json').read_text())
            if ready.get('pid') == pid:
                break
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('Live flow did not open; see logs/visualizer.log')
        time.sleep(.1)
    os.kill(pid, signal.SIGUSR1)
    return pid


async def main():
    async with async_playwright() as pw:
        bounds = desktop_layout()['flow']
        context = await pw.chromium.launch_persistent_context(
            str(ROOT / 'runtime' / 'visualizer-profile'), headless=False, no_viewport=True,
            env=desktop_env(), args=['--no-first-run', '--disable-dev-shm-usage',
                '--app=' + settings()['service_url'] + '/visualizer',
                '--window-position=' + str(bounds['left']) + ',' + str(bounds['top']),
                '--window-size=' + str(bounds['width']) + ',' + str(bounds['height'])])
        page = context.pages[0] if context.pages else await context.new_page()
        if not page.url.startswith(settings()['service_url'] + '/visualizer'):
            await page.goto(settings()['service_url'] + '/visualizer')
        await window_bounds(context, page, bounds)
        closed = asyncio.Event()
        context.on('close', lambda *_: closed.set())
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, closed.set)
        async def activate():
            await window_bounds(context, page, desktop_layout()['flow'])
            await page.bring_to_front()
        loop.add_signal_handler(signal.SIGUSR1, lambda: asyncio.create_task(activate()))
        await page.locator('#flow-app').wait_for()
        await page.wait_for_function('b=>innerWidth>=b.width-64&&innerHeight>=b.height-128', arg=bounds, timeout=5000)
        viewport = await page.evaluate('()=>({width:innerWidth,height:innerHeight})')
        (ROOT / 'runtime' / 'visualizer-ready.json').write_text(json.dumps({'pid': os.getpid(), 'url': page.url,
                                                                         'bounds': bounds, 'viewport': viewport}))
        try:
            await closed.wait()
        finally:
            await context.close()
            (ROOT / 'runtime' / 'visualizer-ready.json').unlink(missing_ok=True)


if __name__ == '__main__':
    asyncio.run(main())
