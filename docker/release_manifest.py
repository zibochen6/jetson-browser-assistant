#!/usr/bin/env python3
"""Record the built/pushed image identity in a jetson-examples release manifest."""
import argparse
import json
import math
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--status', default='candidate-image-built')
    args = parser.parse_args()
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', args.image], text=True))[0]
    if image['Architecture'] != 'arm64' or image['Os'] != 'linux':
        raise RuntimeError('Release image must be Linux ARM64')
    revision = image['Config']['Labels']['org.opencontainers.image.revision']
    if len(revision) != 40 or revision == 'unknown':
        raise RuntimeError('Image is missing a fixed source revision')
    manifest = json.loads(args.manifest.read_text())
    repository = args.image.rsplit(':', 1)[0]
    digest = next((r.split('@', 1)[1] for r in image.get('RepoDigests', []) if r.startswith(repository + '@')), None)
    manifest.update(image=args.image, image_id=image['Id'], digest=digest, source_revision=revision,
                    image_size_bytes=image['Size'], required_free_gib=math.ceil(image['Size'] * 2 / 1024**3) + 2,
                    status=args.status)
    temporary = args.manifest.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, indent=2) + '\n')
    temporary.replace(args.manifest)
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
