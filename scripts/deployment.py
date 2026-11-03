"""Standard-library helpers used before the project environment exists."""
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((ROOT / 'artifacts.lock.json').read_text())
TORCH_GUIDE = 'https://github.com/Seeed-Projects/reComputer-Jetson-for-Beginners/tree/main/3-Basic-Tools-and-Getting-Started/3.5-Pytorch'
TORCH_SHARE = 'https://seeedstudio88-my.sharepoint.com/personal/youjiang_yu_seeedstudio88_onmicrosoft_com/_layouts/15/download.aspx?share=EW2ke8EPcVhGsM2mjCMQOWEBcEuOA45rxNmC0FlkBfhPPg'
BROWSER_URL = 'https://cdn.playwright.dev/builds/cft/156.0.8078.4/linux-arm64/chrome-linux-arm64.zip'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def matches(path, expected):
    path = Path(path)
    return (path.is_file() and path.stat().st_size == expected['bytes']
            and (not expected.get('sha256') or sha256(path) == expected['sha256']))


def download(url, destination, expected, *, offline=False, attempts=3):
    """Resume acknowledged byte ranges; publish only after validation."""
    destination = Path(destination)
    if matches(destination, expected):
        print(f'Already verified: {destination.name}', flush=True)
        return destination
    if offline:
        raise RuntimeError(f'Offline artifact missing or invalid: {destination}')
    if not url.startswith(('https://', 'http://')):
        raise ValueError('Download URL must use HTTP or HTTPS')
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + '.partial')
    if matches(partial, expected):
        os.replace(partial, destination)
        return destination
    if partial.exists() and partial.stat().st_size >= expected['bytes']:
        partial.unlink()
    for attempt in range(attempts):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {'User-Agent': 'jetson-browser-assistant/0.2', 'Accept-Encoding': 'identity'}
            if offset:
                headers['Range'] = f'bytes={offset}-'
            print(f'Downloading {destination.name} ({offset}/{expected["bytes"]} bytes)...', flush=True)
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
                content_type = response.headers.get('Content-Type', '').lower()
                if any(t in content_type for t in ('text/html', 'application/json', 'text/plain')):
                    raise RuntimeError('Download returned a web page, not the requested artifact')
                if response.status == 206:
                    import re
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if not match or int(match[1]) != offset or int(match[3]) != expected['bytes']:
                        raise RuntimeError('Download returned an inconsistent byte range')
                elif response.status != 200:
                    raise RuntimeError(f'Unexpected HTTP status {response.status}')
                with partial.open('ab' if response.status == 206 and offset else 'wb') as output:
                    for block in iter(lambda: response.read(1024 * 1024), b''):
                        output.write(block)
                        if output.tell() > expected['bytes']:
                            raise RuntimeError('Download is larger than the pinned artifact')
            if not matches(partial, expected):
                if partial.stat().st_size >= expected['bytes']:
                    partial.unlink()
                raise RuntimeError('Download size or SHA256 does not match the pinned artifact')
            os.replace(partial, destination)
            print(f'Verified: {destination.name}', flush=True)
            return destination
        except urllib.error.HTTPError as error:
            if error.code == 416:
                partial.unlink(missing_ok=True)
            if error.code in (401, 403, 404) or attempt + 1 == attempts:
                raise RuntimeError(f'Download failed: HTTP {error.code} for {destination.name}') from None
        except (OSError, RuntimeError) as error:
            if attempt + 1 == attempts:
                raise RuntimeError(f'{destination.name}: {error}') from None
        print(f'Retrying {destination.name}; partial download retained.', flush=True)
        time.sleep(attempt + 1)
    raise RuntimeError(f'Download failed: {destination.name}')
