#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [ "$(uname -m)" != aarch64 ]; then
  echo 'Build this CUDA ARM64 release on the Jetson ARM64 build host.' >&2
  exit 1
fi
python3 docker/prepare.py "$@"
revision="$(git rev-parse HEAD)"
image="${JETSON_LAYA_IMAGE:-chenduola6/jetson-laya-browser:0.1.0-rc1-jp62-r36.4.3-arm64}"
docker build --platform linux/arm64 --progress plain \
  --build-arg "SOURCE_REVISION=$revision" -f docker/Dockerfile -t "$image" .
docker image inspect "$image" --format '{{.Id}} {{.Architecture}} {{.Size}}'
echo 'Built locally. Validate GPU, desktop and task results before pushing this release.'
