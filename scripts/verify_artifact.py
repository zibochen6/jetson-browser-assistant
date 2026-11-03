"""Verify a staged installer against the committed deployment manifest."""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('artifact', choices=['torch', 'browser', 'llama_source', 'uv'])
parser.add_argument('path', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
expected = json.loads((root / 'artifacts.lock.json').read_text())[args.artifact]
digest = hashlib.sha256()
with args.path.open('rb') as stream:
    while block := stream.read(8 * 1024 * 1024):
        digest.update(block)
if args.path.stat().st_size != expected['bytes'] or digest.hexdigest() != expected['sha256']:
    raise SystemExit(f'Checksum mismatch: {args.path}')
print(f'Verified {args.artifact}: {digest.hexdigest()}')
