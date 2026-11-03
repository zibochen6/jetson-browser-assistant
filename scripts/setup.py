#!/usr/bin/env python3
"""Idempotent Jetson deployment using only the standard library initially."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from deployment import BROWSER_URL, LOCK, ROOT, TORCH_GUIDE, TORCH_SHARE, download, matches

PACKAGES = ['build-essential', 'cmake', 'ninja-build', 'git', 'curl', 'pkg-config',
            'libcurl4-openssl-dev', 'libopenblas-dev', 'libopenmpi-dev', 'libomp-dev',
            'ffmpeg', 'xterm', 'fonts-noto-cjk', 'unzip', 'ca-certificates', 'x11-utils',
            'x11-xserver-utils']


def host_errors(system, machine, python_version, l4t, cuda_version, memory_kib):
    errors = []
    if system != 'Linux' or machine != 'aarch64':
        errors.append('Run setup on the Jetson (Linux ARM64), not on a Mac or x86 computer.')
    if python_version != '3.10':
        errors.append('System /usr/bin/python3.10 is required; setup will not replace system Python.')
    if 'R36' not in l4t or 'REVISION: 4.' not in l4t:
        errors.append('This release requires JetPack 6.1/6.2 with L4T R36.4.x.')
    if 'release 12.6' not in cuda_version:
        errors.append('CUDA 12.6 is required. Setup does not upgrade CUDA or JetPack.')
    if memory_kib < 14 * 1024 * 1024:
        errors.append('This two-model release targets Orin NX 16GB; lower-memory devices are not supported.')
    return errors


def run(args, *, env=None):
    subprocess.run([str(a) for a in args], cwd=ROOT, env=env, check=True)


def capture(args):
    try:
        return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=15).strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def preflight():
    read = lambda p: Path(p).read_text() if Path(p).is_file() else ''
    memory = dict(line.split(':', 1) for line in read('/proc/meminfo').splitlines())
    errors = host_errors(platform.system(), platform.machine(),
        capture(['/usr/bin/python3.10', '-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")']),
        read('/etc/nv_tegra_release'), capture(['/usr/local/cuda-12.6/bin/nvcc', '--version']),
        int(memory.get('MemTotal', '0 kB').split()[0]))
    model = read('/proc/device-tree/model').replace('\0', '')
    if platform.system() == 'Linux' and 'Orin NX' not in model:
        errors.append('An NVIDIA Jetson Orin NX is required for the validated deployment path.')
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        errors.append('Run setup as your desktop user, without sudo. Only system-package installation uses sudo.')
    if errors:
        raise RuntimeError('\n'.join(errors))
    print(f'Host ready: {model}; Python 3.10; CUDA 12.6', flush=True)
    free = shutil.disk_usage(ROOT).free / (1024 ** 3)
    print(f'Project disk space available: {free:.1f} GiB', flush=True)
    if free < 20:
        print('Note: a first installation should have at least 20 GiB free for downloads, environment and build.', flush=True)
    if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
        print('Note: sign into an X11 desktop before running a visible demo.', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='One-command deployment for Jetson Orin NX 16GB / CUDA 12.6')
    parser.add_argument('--check', action='store_true', help='Read-only host compatibility check; install nothing')
    parser.add_argument('--torch-wheel', type=Path, help='Use an existing pinned PyTorch wheel instead of downloading')
    parser.add_argument('--torch-url', help='Alternate wheel download URL; the pinned SHA256 still applies')
    parser.add_argument('--skip-system-deps', action='store_true', help='System and Chromium libraries are already installed')
    parser.add_argument('--offline', action='store_true', help='Use staged artifacts/caches; make no installation network requests')
    parser.add_argument('--no-start', action='store_true', help='Install and validate without starting or reusing services')
    parser.add_argument('--environment-only', action='store_true', help='Install Python/Chromium, skipping model download/build/start')
    parser.add_argument('--jobs', type=int, default=4, choices=range(1, 9), metavar='1..8', help='llama.cpp build parallelism (default: 4)')
    args = parser.parse_args(argv)
    try:
        preflight()
        if args.check:
            print('Host preflight passed. This check does not claim that dependencies or models are installed.')
            return 0
        started = time.monotonic()
        env = dict(os.environ)
        if args.offline:
            env.update(UV_OFFLINE='1', JETSON_OFFLINE='1')
        if not args.skip_system_deps and not args.offline:
            print('\n[1/6] Installing system libraries (sudo may ask for your password)...', flush=True)
            run(['sudo', 'apt-get', 'update'])
            run(['sudo', 'apt-get', 'install', '-y', *PACKAGES])
        else:
            print('\n[1/6] Using existing system libraries.', flush=True)
        print('\n[2/6] Preparing the pinned ARM64 CUDA PyTorch wheel...', flush=True)
        target = ROOT / 'vendor/wheels' / LOCK['torch']['filename']
        if args.torch_wheel:
            source = args.torch_wheel.expanduser().resolve()
            if not matches(source, LOCK['torch']):
                raise RuntimeError('The supplied PyTorch wheel does not match artifacts.lock.json.')
            target.parent.mkdir(parents=True, exist_ok=True)
            if source != target:
                shutil.copyfile(source, target)
        try:
            download(args.torch_url or TORCH_SHARE, target, LOCK['torch'], offline=args.offline)
        except RuntimeError as error:
            raise RuntimeError(f'{error}\nGet the matching wheel from {TORCH_GUIDE}\nThen rerun: ./setup.sh --torch-wheel /path/to/{target.name}') from None
        print('\n[3/6] Preparing uv and the isolated Python environment...', flush=True)
        managed_uv = ROOT / 'runtime/tools/uv'
        uv = os.environ.get('UV_BIN') or (str(managed_uv) if managed_uv.is_file() else shutil.which('uv'))
        if not uv or capture([uv, '--version']).split()[:2] != ['uv', '0.13.6']:
            run([sys.executable, ROOT / 'scripts/bootstrap_uv.py'], env=env)
            uv = str(ROOT / 'runtime/tools/uv')
        if not (ROOT / 'uv.lock').is_file():
            raise RuntimeError('uv.lock is missing. Use a complete release checkout; setup never resolves new dependency versions.')
        if not (ROOT / '.venv/bin/python').exists():
            run([uv, 'venv', '--python', '/usr/bin/python3.10', ROOT / '.venv'], env=env)
        run([uv, 'sync', '--frozen', '--no-dev'], env=env)
        python = ROOT / '.venv/bin/python'
        run([python, ROOT / 'scripts/gpu_check.py'], env=env)
        print('\n[4/6] Installing the pinned Chromium and desktop libraries...', flush=True)
        archive = ROOT / 'runtime/chromium-linux-arm64-1248.zip'
        browser = capture([str(python), '-c', 'from playwright.sync_api import sync_playwright; p=sync_playwright().start(); print(p.chromium.executable_path); p.stop()'])
        if not browser or not Path(browser).is_file():
            download(BROWSER_URL, archive, LOCK['browser'], offline=args.offline)
            run([python, ROOT / 'scripts/install_browser.py'], env=env)
        if not args.skip_system_deps and not args.offline:
            run([python, '-m', 'playwright', 'install-deps', 'chromium'], env=env)
        if not args.environment_only:
            print('\n[5/6] Downloading/verifying pinned models and building CUDA llama.cpp...', flush=True)
            run([sys.executable, ROOT / 'scripts/fetch_models.py'], env=env)
            env['LLAMA_BUILD_JOBS'] = str(args.jobs)
            run(['bash', ROOT / 'scripts/build_llama.sh'], env=env)
            run([ROOT / '.venv/bin/jetson-browser', 'doctor'], env=env)
            if not args.no_start:
                print('\n[6/6] Loading local models and starting the flight execution service...', flush=True)
                run([ROOT / '.venv/bin/jetson-browser', 'start'], env=env)
        else:
            print('\n[5/6] Models/build skipped (--environment-only).', flush=True)
        (ROOT / 'runtime').mkdir(exist_ok=True)
        (ROOT / 'runtime/setup-report.json').write_text(json.dumps({
            'completed_at': datetime.now(timezone.utc).isoformat(), 'seconds': time.monotonic() - started,
            'offline': args.offline, 'environment_only': args.environment_only,
            'services_requested': not (args.no_start or args.environment_only),
            'note': 'Installation checks, not browser-task acceptance evidence.'}, indent=2) + '\n')
        print('\nSetup complete. On the Jetson X11 desktop, run:\n  ./launch.sh                 # Flight assistant\n  ./launch-whiteboard.sh      # Whiteboard assistant\n  ./status.sh                 # Local service status\n  ./stop.sh                   # Stop all project-owned services\n\nWait for Models ready and Task>, then enter an English task. No screen recording starts automatically.')
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'\nSetup stopped: {error}\nFix the reported step and rerun the same command; verified downloads are reused.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nSetup cancelled. Partial downloads are retained; rerun to continue.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
