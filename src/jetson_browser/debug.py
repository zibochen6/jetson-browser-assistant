"""Loopback-only diagnostic controls; diagnostic actions never count as model success."""
from contextlib import asynccontextmanager
import json
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .browser import Browser
from .config import ROOT, settings

browser = Browser()
folder = ROOT / 'evidence/g0'


def event(data):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'diagnostic-events.jsonl').open('a') as f:
        f.write(json.dumps({'timestamp': time.time(), 'actor': 'diagnostic', **data}, ensure_ascii=False) + '\n')


@asynccontextmanager
async def lifespan(app):
    await browser.start()
    try:
        await browser.navigate(settings()['entry_url'])
    except Exception as e:
        event({'navigation_error': str(e)})
    yield
    await browser.close()


app = FastAPI(lifespan=lifespan)


@app.get('/observe')
async def observe():
    o = await browser.observe()
    result = {'observation_id': o.id, 'page_id': o.page_id, **o.data, 'text': o.text}
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'observation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    await browser.screenshot(folder / 'page.png')
    return result


class Action(BaseModel):
    observation_id: str
    page_id: str
    action_id: str
    text: str | None = None


@app.post('/action')
async def action(req: Action):
    action = next((a for a in browser.last.data['actions'] if a['id'] == req.action_id), None)
    if action is None:
        raise HTTPException(409, 'Action absent; reobserve')
    result = await browser.execute(req.observation_id, req.page_id, action, req.text)
    event({'action': action, 'result': result})
    return result


@app.get('/structure')
async def structure(text: str = 'Search'):
    return await browser.page.evaluate('''text => [...document.querySelectorAll('body *')]
      .filter(e=>e.children.length===0&&e.textContent.trim()===text)
      .slice(0,12).map(e=>({tag:e.tagName,html:e.parentElement?.parentElement?.outerHTML.slice(0,14000)}))''', text)
