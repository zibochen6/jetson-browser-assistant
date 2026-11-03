#!/usr/bin/env bash
# Compatibility entrypoint. New installations should use ./setup.sh.
set -euo pipefail
exec bash "$(dirname -- "${BASH_SOURCE[0]}")/../setup.sh" "$@"
