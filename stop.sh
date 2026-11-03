#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! test -x .venv/bin/jetson-browser; then
  echo 'No project environment found; no services were stopped.'
  exit 0
fi
.venv/bin/jetson-browser whiteboard stop
exec .venv/bin/jetson-browser stop
