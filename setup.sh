#!/usr/bin/env bash
# Configure this checkout on a supported Jetson. No global Python installation.
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 is required. Use a JetPack 6.x Ubuntu 22.04 image.' >&2
  exit 1
fi
exec python3 "$PROJECT_DIR/scripts/setup.py" "$@"
