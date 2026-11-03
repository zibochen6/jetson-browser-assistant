import asyncio
from types import SimpleNamespace
import pytest


@pytest.mark.asyncio
async def test_unresponsive_capture_is_bounded_and_detaches_session(tmp_path, monkeypatch):
    from jetson_browser import browser as module
    from jetson_browser.browser import Browser
    detached=[]
    async def send(*args): await asyncio.Event().wait()
    async def detach(): detached.append(True)
    async def cdp(page): return SimpleNamespace(send=send,detach=detach)
    real_wait=asyncio.wait_for
    async def short_wait(work,timeout): return await real_wait(work,min(timeout,.01))
    monkeypatch.setattr(module,'asyncio',SimpleNamespace(wait_for=short_wait,TimeoutError=asyncio.TimeoutError))
    b=Browser();b.page=object();b.context=SimpleNamespace(new_cdp_session=cdp)
    job=asyncio.create_task(b.screenshot(tmp_path/'shot.png'))
    await asyncio.sleep(.1)
    try:
        assert job.done(), 'Capture must finish without waiting indefinitely for a dead renderer'
        with pytest.raises(asyncio.TimeoutError): await job
        assert detached and not (tmp_path/'shot.png').exists()
    finally:
        if not job.done():
            job.cancel();await asyncio.gather(job,return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_during_flight_final_capture_finishes_trace(tmp_path, monkeypatch):
    from jetson_browser import runner
    from jetson_browser.trace import Trace
    monkeypatch.setattr('jetson_browser.trace.ROOT',tmp_path)
    trace=Trace('test',True,record_video=False)
    entered=asyncio.Event()
    async def parse(*args): raise RuntimeError('Deliberate failure before UI input')
    async def screenshot(*args): entered.set();await asyncio.Event().wait()
    monkeypatch.setattr(runner.Qwen,'parse',parse)
    b=SimpleNamespace(page=SimpleNamespace(url='about:blank',is_closed=lambda:False),
        screenshot=screenshot,is_open=lambda:True)
    session=SimpleNamespace(trace=trace,user_paused_at=None)
    job=asyncio.create_task(runner.run_task(session,b))
    await asyncio.wait_for(entered.wait(),1)
    job.cancel()
    await asyncio.wait_for(job,1)
    assert trace.state['status']=='CANCELLED' and trace.state['finished_at']
