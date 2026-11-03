import asyncio
from contextlib import asynccontextmanager
import json
import re
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .browser import Browser
from .config import ROOT
from .trace import Trace
from .presentation import desktop_layout

browser = Browser()
sessions = {}
presenting = False


class Session:
    def __init__(self, trace, open_details):
        self.trace = trace
        self.open_details = open_details
        self.resume_event = asyncio.Event()
        self.additional_information = ''
        self.worker = None
        self.user_paused_at = None

    async def needs_user(self, reason, missing=None, browser_takeover=False):
        self.resume_event.clear()
        self.user_paused_at = time.monotonic()
        self.trace.state['human_takeover'] |= browser_takeover
        self.trace.set_status('NEEDS_USER', reason, missing=missing or [])
        await self.resume_event.wait()
        self.trace.state['human_wait_seconds'] += time.monotonic() - self.user_paused_at
        self.user_paused_at = None
        self.trace.set_status('RUNNING', 'Clarification received; rechecking the current state', missing=[])
        return self.additional_information


@asynccontextmanager
async def lifespan(app):
    # A process restart never silently resumes browser actions from an old run.
    for path in (ROOT / 'runs').glob('*/result.json'):
        try:
            state = json.loads(path.read_text())
            if state.get('status') in ['RUNNING', 'NEEDS_USER']:
                state.update(status='FAILED', message='Execution service restarted; the previous task was not resumed automatically', error='service_restarted')
                path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except (OSError, ValueError):
            pass
    yield
    active = [s.worker for s in sessions.values() if s.worker and not s.worker.done()]
    for task in active:
        task.cancel()
    await asyncio.gather(*active, return_exceptions=True)
    await browser.close()


app = FastAPI(lifespan=lifespan)


class Submit(BaseModel):
    request: str = Field(min_length=2, max_length=3000)
    keep_open: bool = False
    site: Literal['trip'] = 'trip'
    open_details: bool = True
    submitted_at: float | None = None
    startup_seconds: dict = Field(default_factory=dict)
    timing_scope: Literal['legacy', 'after_preload'] = 'legacy'
    record_video: bool | None = None


class Resume(BaseModel):
    additional_information: str = Field(default='', max_length=2000)


class Presentation(BaseModel):
    enabled: bool = True


def run_folder(task_id):
    if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{8}', task_id):
        raise HTTPException(404, 'Run not found')
    return ROOT / 'runs' / task_id


@app.get('/visualizer')
def visualizer():
    return FileResponse(Path(__file__).parent / 'static' / 'visualizer.html')


@app.get('/visualizer/{asset}')
def visualizer_asset(asset):
    if asset not in ('visualizer.css', 'visualizer.js'):
        raise HTTPException(404)
    return FileResponse(Path(__file__).parent / 'static' / asset)


@app.get('/runs')
def runs(limit: int = Query(default=20, ge=1, le=100)):
    found = []
    for path in sorted((ROOT / 'runs').glob('*/result.json'), reverse=True):
        if len(found) >= limit:
            break
        try:
            data = json.loads(path.read_text())
            found.append({k: data.get(k) for k in ('id', 'status', 'request', 'total_seconds')})
        except (OSError, ValueError):
            continue
    return {'runs': found}


@app.post('/presentation')
async def presentation(req: Presentation):
    global presenting
    # Window arrangement is CLI-only. The flow page uses GET requests only.
    if presenting or any(s.worker and not s.worker.done() for s in sessions.values()):
        raise HTTPException(409, 'Window setup requires an idle execution service')
    presenting = True
    try:
        await browser.set_presentation(req.enabled)
    finally:
        presenting = False
    return {'enabled': req.enabled, 'layout': desktop_layout() if req.enabled else None}


def get_session(task_id):
    if task_id not in sessions:
        raise HTTPException(404, 'Task is not owned by the current execution service')
    return sessions[task_id]


@app.get('/health')
def health():
    active = [s.trace.id for s in sessions.values() if s.worker and not s.worker.done()]
    return {'ready': True, 'service': 'jetson-browser', 'active_tasks': active, 'site': 'trip', 'browser_open': browser.is_open(),
            'latest_task_id': next(reversed(sessions), None)}


@app.post('/tasks')
async def submit(req: Submit):
    if presenting:
        raise HTTPException(409, 'Window setup is in progress; submit the task when setup finishes')
    if any(s.worker and not s.worker.done() for s in sessions.values()):
        raise HTTPException(409, 'A task is still running or awaiting user input; resume or cancel it first')
    trace = Trace(req.request, req.keep_open, req.submitted_at, req.startup_seconds,
                  timing_scope=req.timing_scope, record_video=req.record_video)
    session = Session(trace, req.open_details)
    sessions[trace.id] = session
    from .runner import run_task
    session.worker = asyncio.create_task(run_task(session, browser))
    return {'id': trace.id}


@app.get('/tasks/{task_id}')
async def state(task_id):
    if task_id in sessions:
        trace = sessions[task_id].trace
        result = dict(trace.state)
        if result['status'] in ['RUNNING', 'NEEDS_USER']:
            result['total_seconds'] = max(0, time.time() - trace.submitted_at)
            result['browser_open'] = browser.is_open()
        return result
    path = run_folder(task_id) / 'result.json'
    if not path.exists():
        raise HTTPException(404)
    return json.loads(path.read_text())


@app.get('/tasks/{task_id}/events')
def events(task_id, after: int = Query(default=0, ge=0)):
    if task_id in sessions:
        selected = sessions[task_id].trace.events[after:after + 100]
    else:
        path = run_folder(task_id) / 'events.jsonl'
        if not path.exists():
            raise HTTPException(404, 'Run events not found')
        selected = []
        with path.open() as stream:
            for index, line in enumerate(stream):
                if index < after:
                    continue
                if len(selected) >= 100:
                    break
                try:
                    selected.append(json.loads(line))
                except ValueError:
                    break  # A partial last line can be retried on the next read.
    return {'events': selected, 'next_cursor': after + len(selected)}


@app.post('/tasks/{task_id}/resume')
async def resume(task_id, req: Resume):
    s = get_session(task_id)
    if s.trace.state['status'] != 'NEEDS_USER':
        raise HTTPException(409, 'This task is not waiting for user input')
    s.additional_information = req.additional_information
    s.trace.event('user', 'User requested resume', additional_information=req.additional_information)
    s.resume_event.set()
    return {'accepted': True}


@app.post('/tasks/{task_id}/cancel')
async def cancel(task_id):
    s = get_session(task_id)
    if s.worker and not s.worker.done():
        s.worker.cancel()
        await asyncio.gather(s.worker, return_exceptions=True)
    return s.trace.state
