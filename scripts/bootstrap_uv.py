"""Install locked uv inside this checkout, without global changes."""
import json
import os
import urllib.request
import zipfile

from deployment import LOCK, ROOT, download

artifact = LOCK['uv']
staged = ROOT / 'vendor/wheels' / artifact['filename']
offline = os.environ.get('JETSON_OFFLINE') == '1'
url = ''
if not offline:
    with urllib.request.urlopen('https://pypi.org/pypi/uv/0.13.6/json', timeout=30) as response:
        metadata = json.load(response)
    entry = next(f for f in metadata['urls'] if f['filename'] == artifact['filename'])
    if entry['digests']['sha256'] != artifact['sha256']:
        raise SystemExit('PyPI uv checksum differs from artifacts.lock.json')
    url = entry['url']
download(url, staged, artifact, offline=offline)
destination = ROOT / 'runtime/tools'
destination.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(staged) as archive:
    for executable in ('uv', 'uvx'):
        members = [n for n in archive.namelist() if n.endswith('/' + executable)]
        if len(members) != 1:
            raise SystemExit('Unexpected uv wheel layout')
        path = destination / executable
        path.write_bytes(archive.read(members[0]))
        path.chmod(0o755)
print('Pinned uv installed in runtime/tools (system Python unchanged).')
