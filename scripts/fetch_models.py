#!/usr/bin/env python3
"""Download pinned public model artifacts, verify checksums, support resuming."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def fetch(job):
    repo, revision, entry, folder = job
    dst = ROOT / folder / entry['path']
    dst.parent.mkdir(parents=True, exist_ok=True)
    expected = entry.get('sha256')
    if dst.exists() and dst.stat().st_size == entry['bytes']:
        if not expected or sha256(dst) == expected:
            return str(dst)
    if os.environ.get('JETSON_OFFLINE') == '1':
        raise RuntimeError(f'Offline model file missing or invalid: {dst}')
    tmp = dst.with_name(dst.name + '.partial')
    if tmp.exists() and tmp.stat().st_size == entry['bytes']:
        if not expected or sha256(tmp) == expected:
            os.replace(tmp, dst)
            print(f"verified resumed {dst.name}", flush=True)
            return str(dst)
        tmp.unlink()
    if tmp.exists() and tmp.stat().st_size > entry['bytes']:
        tmp.unlink()
    endpoint = os.environ.get('JETSON_MODEL_DOWNLOAD_ENDPOINT', 'https://huggingface.co').rstrip('/')
    url = f"{endpoint}/{repo}/resolve/{revision}/{entry['path']}"
    for attempt in range(4):
        try:
            offset = tmp.stat().st_size if tmp.exists() else 0
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as src:
                mode = 'ab' if offset and src.status == 206 else 'wb'
                with tmp.open(mode) as out:
                    while chunk := src.read(4 * 1024 * 1024):
                        out.write(chunk)
            if tmp.stat().st_size != entry['bytes']:
                raise RuntimeError(f"size mismatch {tmp.stat().st_size}/{entry['bytes']}")
            if expected:
                digest = sha256(tmp)
                if digest != expected:
                    tmp.unlink()
                    raise RuntimeError('SHA256 mismatch')
            os.replace(tmp, dst)
            print(f"verified {repo}/{entry['path']} ({entry['bytes']} bytes)", flush=True)
            return str(dst)
        except Exception as e:
            print(f"retry {attempt + 1}: {entry['path']}: {e}", flush=True)
            if attempt == 3:
                raise
            time.sleep(2)


if __name__ == '__main__':
    jobs = []
    for name, folder in [('laya-browser', 'models/laya-browser'), ('Qwen3.5-4B-MTP-GGUF', 'models/qwen')]:
        m = json.loads((ROOT / f'manifest-{name}.json').read_text())
        for f in m['files']:
            if name == 'laya-browser':
                wanted = f['path'] in ['config.json', 'rl_agent_config.json', 'model.safetensors', 'laya_browser.py', 'modeling_laya_browser.py', 'README.md'] or f['path'].startswith(('encoder/', 'tokenizer/'))
            else:
                wanted = f['path'] == 'Qwen3.5-4B-Q4_K_M.gguf'
            if wanted:
                jobs.append((m['repo'], m['revision'], f, folder))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(fetch, jobs))
