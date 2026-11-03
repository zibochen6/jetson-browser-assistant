"""Record environment facts without changing JetPack, Python, or desktop settings."""
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=20)
        return {'exit_code': p.returncode, 'output': (p.stdout + p.stderr).strip()}
    except Exception as e:
        return {'error': str(e)}


def read(path):
    p = Path(path)
    return p.read_text().replace('\x00', '').strip() if p.exists() else None


result = {
    'timestamp': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
    'machine': platform.machine(), 'python': platform.python_version(),
    'model': read('/proc/device-tree/model'), 'l4t': read('/etc/nv_tegra_release'),
    'os': read('/etc/os-release'), 'cuda': command(['/usr/local/cuda-12.6/bin/nvcc', '--version']),
    'gpu': command(['nvidia-smi']), 'memory': command(['free', '-h']), 'disk': command(['df', '-h', '.']),
    'desktop': command(['loginctl', 'show-session', '1', '-p', 'Type', '-p', 'Active', '-p', 'Service']),
    'packages': {name: importlib.metadata.version(name) for name in ['torch', 'transformers', 'laya', 'playwright', 'fastapi']},
    'docker': shutil.which('docker'), 'ethernet_speed_mbps': read('/sys/class/net/enP8p1s0/speed'),
    'deployment': 'native uv environments; Docker not required',
}
assert result['machine'] == 'aarch64' and result['model'] and 'Orin NX' in result['model'], 'Not target Jetson'
Path('evidence').mkdir(exist_ok=True)
Path('evidence/environment.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
