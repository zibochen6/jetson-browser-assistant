"""GPU-only service retaining the pinned upstream browser wrapper/input format."""
import importlib.util
import time
from contextlib import asynccontextmanager
import threading

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .config import ROOT

model = None
load_seconds = None
lock = threading.Lock()


@asynccontextmanager
async def lifespan(app):
    global model, load_seconds
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable: Laya CPU fallback is disabled')
    path = ROOT / 'models/laya-browser'
    spec = importlib.util.spec_from_file_location('pinned_laya_browser', path / 'laya_browser.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    t = time.perf_counter()
    model = module.LayaBrowser.from_pretrained(str(path), device='cuda', fast=False)
    assert next(model.agent.model.parameters()).is_cuda
    torch.cuda.synchronize()
    load_seconds = time.perf_counter() - t
    yield


app = FastAPI(lifespan=lifespan)


class Request(BaseModel):
    page: dict
    goal: str
    history: list[dict] = Field(default_factory=list)


@app.get('/health')
def health():
    return {'ready': model is not None, 'device': 'cuda', 'model': 'cklxx/laya-browser v19s', 'load_seconds': load_seconds, 'fast': False}


@app.post('/decide')
def decide(req: Request):
    import torch
    with lock, torch.inference_mode():
        t = time.perf_counter()
        result = model.decide(req.page, req.goal, req.history)
        torch.cuda.synchronize()
        result['latency_ms'] = (time.perf_counter() - t) * 1000
        return result
