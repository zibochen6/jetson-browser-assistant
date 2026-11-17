#!/usr/bin/env python3
"""Stage pinned image inputs; --artifacts reuses files after size/SHA verification."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from deployment import LOCK, TORCH_SHARE, BROWSER_URL, download, matches


def model_entries():
    for name, directory in [('laya-browser', 'laya-browser'), ('Qwen3.5-4B-MTP-GGUF', 'qwen')]:
        manifest = json.loads((ROOT / f'manifest-{name}.json').read_text())
        for entry in manifest['files']:
            p = entry['path']
            if (name == 'laya-browser' and (p in ['config.json', 'rl_agent_config.json', 'model.safetensors',
                    'laya_browser.py', 'modeling_laya_browser.py', 'README.md'] or p.startswith(('encoder/', 'tokenizer/')))
                    or name != 'laya-browser' and p == 'Qwen3.5-4B-Q4_K_M.gguf'):
                yield Path('models') / directory / p, entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, help='Reuse a matching existing deployment; never copy its environment/profile')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    entries = list(model_entries())
    if args.verify_only:
        for path, entry in entries:
            if not matches(ROOT / path, entry):
                raise RuntimeError('Missing/invalid model artifact: ' + str(path))
        print('All image model files match pinned manifests.')
        return
    extra = [(Path('vendor/wheels') / LOCK[k]['filename'], LOCK[k]) for k in ('torch', 'uv')]
    extra += [(Path('runtime/chromium-linux-arm64-1248.zip'), LOCK['browser']),
              (Path('runtime/llama-source.tar.gz'), LOCK['llama_source'])]
    for relative, entry in entries + extra:
        target = ROOT / relative
        if matches(target, entry):
            continue
        source = args.artifacts / relative if args.artifacts else None
        if source and matches(source, entry):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            print('Verified and reused:', relative, flush=True)
    for relative, entry in extra:
        if matches(ROOT / relative, entry):
            continue
        urls = {'torch': TORCH_SHARE, 'browser': BROWSER_URL,
                'llama_source': 'https://codeload.github.com/ggml-org/llama.cpp/tar.gz/785322d17f2d51e5185cf996a1f4e46d87640841'}
        key = next(k for k in LOCK if LOCK[k] == entry)
        if key == 'uv':
            import urllib.request
            with urllib.request.urlopen('https://pypi.org/pypi/uv/0.13.6/json', timeout=30) as response:
                metadata = json.load(response)
            url = next(f['url'] for f in metadata['urls'] if f['filename'] == entry['filename'])
        else:
            url = urls[key]
        download(url, ROOT / relative, entry)
    subprocess.run([sys.executable, ROOT / 'scripts/fetch_models.py'], check=True)


if __name__ == '__main__':
    main()
