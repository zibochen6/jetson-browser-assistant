#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! test -x .venv/bin/jetson-browser; then
  echo 'Project environment is missing. Run ./setup.sh first.' >&2
  exit 1
fi
exec .venv/bin/jetson-browser status "$@"
