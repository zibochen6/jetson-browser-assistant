"""Compare the same local board with GPU/software browser rendering, no models.

Imports an already exported real scene via the file input and performs read-only
exports. These are renderer measurements, not model/task acceptance results.
"""
import asyncio
import json
import time
from pathlib import Path
from jetson_browser.browser import Browser
from jetson_browser.config import ROOT


def memory():
    values={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        parts=line.split();values[parts[0].rstrip(':')]=int(parts[1])
    return {'system_used_kib':values['MemTotal']-values['MemAvailable'],
            'swap_used_kib':values['SwapTotal']-values['SwapFree']}


async def main():
    results=[]
    path=ROOT/'whiteboard-runs/20261103-142220-2ee06168/scene.excalidraw'
    for mode in ('hardware','software'):
        before=memory()
        browser=Browser(profile_dir=ROOT/('runtime/whiteboard-render-'+mode),
                        extra_args=['--disable-gpu'] if mode=='software' else [])
        samples=[]
        async def sampler():
            while True:
                samples.append(memory());await asyncio.sleep(.5)
        sampling=asyncio.create_task(sampler())
        measurements=[]
        try:
            await browser.start()
            await browser.navigate('http://127.0.0.1:8793/whiteboard/')
            await browser.page.wait_for_function('()=>!!window.whiteboard')
            await browser.page.get_by_test_id('open-scene-file').set_input_files(str(path))
            await browser.page.wait_for_function('()=>whiteboard.read().elements.length===11')
            for i in range(4):
                started=time.perf_counter()
                await browser.page.evaluate('whiteboard.png()')
                await browser.screenshot(ROOT/f'runtime/whiteboard-render-{mode}.png')
                measurements.append(time.perf_counter()-started)
            await asyncio.sleep(1)
        finally:
            await browser.close()
            sampling.cancel()
            await asyncio.gather(sampling,return_exceptions=True)
        after=memory()
        result={'renderer':mode,'model_calls':0,'before':before,'after_close':after,
            'peak':max((s['system_used_kib'] for s in samples),default=before['system_used_kib']),
            'samples':samples,'export_seconds':measurements}
        results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k!='samples'}),flush=True)
        await asyncio.sleep(1)
    (ROOT/'runtime/whiteboard-rendering-comparison.json').write_text(json.dumps(results,indent=2))


asyncio.run(main())
