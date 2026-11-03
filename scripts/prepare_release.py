#!/usr/bin/env python3
"""Export public source with a fresh-history boundary; never copy local run data."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TOP = {'README.md', 'README.zh-CN.md', 'LICENSE', 'NOTICE', 'THIRD_PARTY.md',
       'CONTRIBUTING.md', 'SECURITY.md', '.gitignore', 'pyproject.toml', 'uv.lock',
       'config.json', 'artifacts.lock.json', 'manifest-laya-browser.json',
       'manifest-Qwen3.5-4B-MTP-GGUF.json', 'manifest-whiteboard-assets.json',
       'requirements-test.txt', 'setup.sh', 'launch.sh', 'launch-whiteboard.sh',
       'status.sh', 'stop.sh'}
DOCS = {'installation.md', 'usage.md', 'architecture.md', 'troubleshooting.md',
        'validation-summary.md', 'release-validation.md', 'whiteboard.md', 'demo-en.md', 'live-flow.md'}
DIRECTORIES = {'src', 'tests', 'scripts', 'frontend', 'examples', '.github'}


def public_path(path):
    p = Path(path)
    if p.is_absolute() or '..' in p.parts:
        return False
    if any(part in {'node_modules', '__pycache__', '.venv', '.venv-test', '.git', '.pytest_cache'} for part in p.parts):
        return False
    return (path in TOP or (len(p.parts) > 1 and p.parts[0] in DIRECTORIES)
            or (len(p.parts) == 2 and p.parts[0] == 'docs' and p.name in DOCS))


def export(destination):
    destination = Path(destination).expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError('Use a separate export directory outside this checkout.')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Export destination must be empty; existing files will not be removed.')
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT).decode().split('\0')
    chosen = sorted({p for p in names if p and public_path(p) and (ROOT / p).is_file()})
    for name in chosen:
        source = ROOT / name
        if source.is_symlink() or ROOT not in source.resolve().parents:
            raise ValueError('Refusing source symlink: ' + name)
    required = TOP
    if required - set(chosen):
        raise ValueError('Release files missing: ' + ', '.join(sorted(required - set(chosen))))
    destination.mkdir(parents=True, exist_ok=True)
    for name in chosen:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    print(f'Exported {len(chosen)} public source files to {destination}')
    print('Local evidence, profiles, models, environments and original Git history were not copied.')
    return chosen


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        export(args.destination)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Export stopped: {error}\n')
