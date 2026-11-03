"""Isolated loopback whiteboard service. Never owns the flight browser or models."""
import asyncio
from contextlib import asynccontextmanager
import json
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import ROOT
from .trace import Trace
from .whiteboard_browser import WhiteboardBrowser
from .whiteboard_runner import run_task

browser = WhiteboardBrowser()
sessions = {}
opening = False


class Session:
    def __init__(self, trace):
        self.trace, self.worker = trace, None
        self.resume_event = asyncio.Event()
        self.information = ''

    async def needs_user(self, reason):
        self.resume_event.clear()
        start = time.monotonic()
        self.trace.set_status('NEEDS_USER', reason)
        try:
            await self.resume_event.wait()
        finally:
            self.trace.state['human_wait_seconds'] += time.monotonic() - start
        self.trace.set_status('RUNNING', 'Clarification received; re-reading the canvas')
        return self.information


@asynccontextmanager
async def lifespan(app):
    for p in (ROOT / 'whiteboard-runs').glob('*/result.json'):
        try:
            d = json.loads(p.read_text())
            if d['status'] in ('RUNNING', 'NEEDS_USER'):
                d.update(status='FAILED', message='Whiteboard service restarted; no actions automatically resumed')
                p.write_text(json.dumps(d, indent=2))
        except (ValueError, OSError):
            pass
    yield
    workers = [s.worker for s in sessions.values() if not s.worker.done()]
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    await browser.close()


app = FastAPI(lifespan=lifespan)


@app.middleware('http')
async def local_only_resources(request, call_next):
    response = await call_next(request)
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
        "connect-src 'self'; worker-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'self'")
    if not request.url.path.startswith('/whiteboard/assets/') and not request.url.path.startswith('/whiteboard/fonts/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


class Submit(BaseModel):
    request: str = Field(min_length=2, max_length=3000)
    submitted_at: float | None = None


class Information(BaseModel):
    additional_information: str = Field(default='', max_length=2000)


class OpenFile(BaseModel):
    path: str


def active():
    return [s.trace.id for s in sessions.values() if not s.worker.done()]


def folder(run_id):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{8}', run_id):
        raise HTTPException(404)
    p = ROOT / 'whiteboard-runs' / run_id
    if not (p / 'result.json').exists():
        raise HTTPException(404)
    return p


@app.get('/health')
def health():
    return {'ready': True, 'service': 'jetson-whiteboard', 'active_tasks': active(),
        'browser_open': browser.is_open(), 'latest_task_id': next(reversed(sessions), None)}


@app.get('/board')
async def board():
    if not browser.is_open():
        raise HTTPException(409, 'Whiteboard is not open')
    return await browser.read()


@app.post('/open')
async def open_file(req: OpenFile):
    global opening
    if active() or opening:
        raise HTTPException(409, 'Opening a file requires an idle whiteboard')
    p = Path(req.path).expanduser().resolve()
    if not p.is_file() or p.suffix != '.excalidraw' or p.stat().st_size > 10 * 1024 * 1024:
        raise HTTPException(400, 'Choose an existing .excalidraw file under 10MB')
    opening = True
    try:
        return await browser.import_file(p)
    except Exception as error:
        raise HTTPException(400, 'Scene import failed: ' + str(error)) from error
    finally:
        opening = False


@app.post('/tasks')
async def submit(req: Submit):
    if active() or opening:
        raise HTTPException(409, 'A whiteboard task is running or awaiting clarification')
    trace = Trace(req.request, True, req.submitted_at, timing_scope='after_preload', record_video=False,
                  scene='whiteboard', runs_root='whiteboard-runs')
    session = Session(trace)
    sessions[trace.id] = session
    session.worker = asyncio.create_task(run_task(session, browser))
    return {'id': trace.id}


@app.get('/tasks/{run_id}')
def state(run_id):
    if run_id in sessions:
        d = dict(sessions[run_id].trace.state)
        if d['status'] in ('RUNNING', 'NEEDS_USER'):
            d['total_seconds'] = max(0, time.time() - sessions[run_id].trace.submitted_at)
        return d
    return json.loads((folder(run_id) / 'result.json').read_text())


@app.get('/tasks/{run_id}/events')
def events(run_id, after: int = Query(0, ge=0)):
    if run_id in sessions:
        selected = sessions[run_id].trace.events[after:after + 100]
    else:
        lines = (folder(run_id) / 'events.jsonl').read_text().splitlines()
        selected = [json.loads(line) for line in lines[after:after + 100]]
    return {'events': selected, 'next_cursor': after + len(selected)}


@app.post('/tasks/{run_id}/cancel')
async def cancel(run_id):
    if run_id not in sessions:
        raise HTTPException(404)
    s = sessions[run_id]
    if not s.worker.done():
        s.worker.cancel()
        await asyncio.gather(s.worker, return_exceptions=True)
    return s.trace.state


@app.post('/tasks/{run_id}/resume')
async def resume(run_id, req: Information):
    if run_id not in sessions or sessions[run_id].trace.state['status'] != 'NEEDS_USER':
        raise HTTPException(409, 'The task is not waiting for clarification')
    s = sessions[run_id]
    s.information = req.additional_information
    s.resume_event.set()
    return {'accepted': True}


app.mount('/whiteboard', StaticFiles(directory=Path(__file__).parent / 'static/whiteboard', html=True), name='whiteboard')
