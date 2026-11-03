"""Install the exact Playwright ARM64 browser archive downloaded on the deployment host."""
import hashlib
import json
from pathlib import Path
import stat
import zipfile

root = Path(__file__).resolve().parents[1]
archive = root / 'runtime/chromium-linux-arm64-1248.zip'
destination = Path.home() / '.cache/ms-playwright/chromium-1248'
destination.mkdir(parents=True, exist_ok=True)
(root / 'evidence').mkdir(exist_ok=True)
h = hashlib.sha256()
with archive.open('rb') as f:
    while b := f.read(8 * 1024 * 1024):
        h.update(b)
expected = json.loads((root / 'artifacts.lock.json').read_text())['browser']
assert archive.stat().st_size == expected['bytes'] and h.hexdigest() == expected['sha256'], 'Browser archive checksum mismatch'
with zipfile.ZipFile(archive) as z:
    for entry in z.infolist():
        target = (destination / entry.filename).resolve()
        assert destination.resolve() in target.parents, 'Unsafe archive path'
        z.extract(entry, destination)
        mode = entry.external_attr >> 16
        if mode:
            target.chmod(stat.S_IMODE(mode))
(destination / 'INSTALLATION_COMPLETE').touch()
(root / 'evidence/browser-install.json').write_text(json.dumps({
    'playwright': '1.64.1', 'revision': '1248', 'version': '156.0.8078.4',
    'source': 'https://cdn.playwright.dev/builds/cft/156.0.8078.4/linux-arm64/chrome-linux-arm64.zip',
    'sha256': h.hexdigest(), 'executable': str(destination / 'chrome-linux-arm64/chrome'),
}, indent=2))
print(destination)
