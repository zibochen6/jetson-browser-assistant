# Public packaging validation — 2026-11-03

This records deployment/packaging checks, separately from the original real-site
and whiteboard task measurements in [validation-summary.md](validation-summary.md).
No new demonstration recording, MTP comparison or model replacement was made.

## Development Mac

- Full model-free suite: **105 passed in22.87s** using Python3.10 and the pinned
  Playwright1.64.1. Includes actual local Chromium lifecycle/DOM tests; no model
  weights are loaded by the suite.
- Eleven installer/config/process checks cover HTTP range resume, ignored/malformed
  ranges, HTML rejection, SHA256 rejection, offline behavior, incompatible hosts,
  release file selection, local configuration, current-user desktop variables and
  process ownership/port conflicts.
- Shell syntax, Python undefined-name checks and git whitespace checks passed.
- The complete Seeed PyTorch2.7 ARM64 wheel was downloaded from the public endpoint
  behind the official guide and matched the266,741,529-byte size and locked SHA256.
  This establishes that endpoint/artifact at test time, not permanent availability.
- The production installer correctly rejects macOS without installing anything.

## Actual Jetson, isolated checkout

- Orin NX16GB / L4T36.4.3 / CUDA12.6 / system Python3.10.12 host preflight passed.
- A separate checkout created a **new uv environment** from the committed lock,
  installed48 production packages and passed real torch2.7.0 CUDA matrix computation
  on Orin, compute capability8.7. The pinned uv download/bootstrap also passed.
- Used `--environment-only --no-start --skip-system-deps` with the existing matching
  wheel. Host system libraries and the Playwright browser cache were reused.
- Full cached/offline setup then passed using `--offline --no-start --skip-system-deps`.
  It validated the existing pinned model files and reused the matching CUDA
  llama.cpp build. Test-only links pointed to those pre-existing artifacts; they
  are not part of the exported source.
- Full test suite on this target checkout: **105 passed in39.17s**. Test interpreter
  came from the existing validated installation; source imports came from the new
  checkout. The fresh production environment intentionally excludes test packages.
- After the final installer/CLI/process refinements,30 focused checks passed on
  the Jetson in2.91s and on the Mac in2.65s; cached/offline setup was rerun successfully.
- Status correctly identified all four occupied original ports as belonging to
  another checkout. It did not claim those services as its own or stop them.

This is **not a factory-reset/cold-OS installation**, a full fresh model download
on the Jetson, or a new end-to-end model-task benchmark. The existing whiteboard
was waiting for user clarification, so its canvas and model processes were retained.
The public source excludes raw evidence, private host paths, profiles, installed
packages, models, wheels and original development Git history.
