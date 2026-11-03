"""Four real Jetson feasibility experiments; not a production drawing script."""
import asyncio
import json
import time
from jetson_browser.config import ROOT, desktop_env
from jetson_browser.llm import laya_decide
from playwright.async_api import async_playwright


async def drag(page, a, b):
    await page.mouse.move(*a)
    await page.mouse.down()
    try:
        await page.mouse.move(*b, steps=18)
    finally:
        await page.mouse.up()


async def main():
    out = ROOT / 'runtime/whiteboard-m0'
    out.mkdir(exist_ok=True)
    report = {'started_at': time.time(), 'platform': 'Jetson Orin NX', 'experiments': [], 'decisions': []}
    async with async_playwright() as p:
        c = await p.chromium.launch_persistent_context(str(ROOT/'runtime/whiteboard-m0-profile'),
            headless=False, viewport={'width':1440,'height':1000}, env=desktop_env())
        page = c.pages[0]
        page.set_default_timeout(12000)
        external, errors = [], []
        page.on('request', lambda r: external.append(r.url) if r.url.startswith('http') and not r.url.startswith('http://127.0.0.1:8793/') else None)
        page.on('pageerror', lambda e: errors.append(str(e)))
        try:
            await page.goto('http://127.0.0.1:8793/whiteboard/')
            await page.wait_for_function('()=>!!window.whiteboard')
            report['experiments'].append({'id':1,'status':'PASS','external_requests':external})
            await page.get_by_test_id('toolbar-rectangle').locator('..').click()
            await drag(page,(500,300),(700,420))
            await page.mouse.dblclick(600,360)
            await page.keyboard.insert_text('Camera')
            await page.keyboard.press('Escape')
            await page.mouse.click(500,330)
            report['property_controls'] = await page.locator('button,input').evaluate_all('(es)=>es.map(e=>({label:e.getAttribute("aria-label"),title:e.getAttribute("title"),testid:e.getAttribute("data-testid"),type:e.type,value:e.value}))')
            (out/'controls.json').write_text(json.dumps(report['property_controls'],indent=2))
            # Read the actual visible background color input, not component internals.
            await page.screenshot(path=str(out/'properties.png'))
            report['before_color'] = await page.evaluate('whiteboard.read()')
            await page.get_by_test_id('color-top-pick-#b2f2bb').click()
            await page.keyboard.press('Escape')
            await drag(page,(500,330),(560,390))
            after = await page.evaluate('whiteboard.read()')
            rect = next(e for e in after['elements'] if e['type']=='rectangle')
            assert rect['backgroundColor']=='#b2f2bb' and abs(rect['x']-560)<2
            assert any(e.get('text')=='Camera' and e.get('containerId')==rect['id'] for e in after['elements'])
            report['experiments'].append({'id':2,'status':'PASS','scene':after})
            await page.keyboard.press('Escape')
            await drag(page,(560,390),(680,470))
            moved=await page.evaluate('whiteboard.read()')
            moved_rect=next(e for e in moved['elements'] if e['type']=='rectangle')
            assert moved_rect['id']==rect['id'] and abs(moved_rect['x']-680)<2
            report['experiments'].append({'id':3,'status':'PASS','external_ui_scene':moved})
            for color,hexcolor in [('blue','#a5d8ff'),('green','#b2f2bb')]:
                s=await page.evaluate('whiteboard.read()')
                r=next(e for e in s['elements'] if e['type']=='rectangle')
                await page.mouse.click(r['x'],r['y']+30)
                actions=[]
                for i,(name,h) in enumerate([('red','#ffc9c9'),('green','#b2f2bb'),('blue','#a5d8ff'),('yellow','#ffec99')]):
                    assert await page.get_by_test_id('color-top-pick-'+h).is_visible()
                    actions.append({'id':'color_'+name,'kind':'click','node':str(i),'role':'button',
                        'label':f'Camera background: {name}', 'source':'visible_background_swatch','hex':h})
                if color=='green': actions.reverse()
                observation={'url':page.url,'title':'Local whiteboard','text':json.dumps({'Camera':{'x':r['x'],'y':r['y'],'background':r['backgroundColor']}}),'actions':actions}
                goal=f'Make the Camera rectangle background {color}. Keep its text and position.'
                d=await laya_decide(observation,goal,[])
                entry={'page':observation,'goal':goal,'raw_response':d}
                report['decisions'].append(entry)
                assert d['action']['id']=='color_'+color,d
                await page.get_by_test_id('color-top-pick-'+d['action']['hex']).click()
                entry['actual_after']=await page.evaluate('whiteboard.read()')
                assert next(e for e in entry['actual_after']['elements'] if e['type']=='rectangle')['backgroundColor']==hexcolor
            for target in ['center','left']:
                await page.keyboard.press('Escape')
                s=await page.evaluate('whiteboard.read()')
                r=next(e for e in s['elements'] if e['type']=='rectangle')
                actions=[{'id':'move_'+name,'node':str(i),'kind':'click','role':'button',
                    'label':f'Move Camera to {name}', 'source':'canvas_mouse_gesture_capability','x':x}
                    for i,(name,x) in enumerate([('left',420),('center',760),('right',1080)])]
                observation={'url':page.url,'title':'Local whiteboard','text':f'Camera at ({r["x"]},{r["y"]}). Canvas drag operations below use actual mouse input.','actions':actions}
                goal=f'Move Camera to the {target} of the canvas. Keep its color and label.'
                d=await laya_decide(observation,goal,[])
                entry={'page':observation,'goal':goal,'raw_response':d}
                report['decisions'].append(entry)
                assert d['action']['id']=='move_'+target,d
                await drag(page,(r['x'],r['y']+30),(d['action']['x'],r['y']+30))
                entry['actual_after']=await page.evaluate('whiteboard.read()')
                actual=next(e for e in entry['actual_after']['elements'] if e['type']=='rectangle')
                assert abs(actual['x']-d['action']['x'])<2
            report['experiments'].append({'id':4,'status':'PASS','real_laya_decisions':len(report['decisions'])})
            await page.screenshot(path=str(out/'final.png'))
            print(json.dumps({'experiments':report['experiments'][-1],'errors':errors,'external':external}),flush=True)
        finally:
            report.update(external_requests=external,errors=errors,finished_at=time.time())
            (out/'report.json').write_text(json.dumps(report,indent=2))
            await c.close()


asyncio.run(main())
