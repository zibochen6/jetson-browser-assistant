# Contributing

Use small changes with an explicit behavior and validation. Keep the original
Laya candidate format, meaningful alternatives, UI-only whiteboard edits and the
independent verifiers. Do not replace decisions with a forced script while calling
it a model demonstration. Don't change model weights/MTP defaults as a packaging fix.

## Model-free checks (Mac / Linux / CI)

Use Python3.10 and a separate test environment. No weights or Jetson torch wheel
are needed for these tests:

```bash
python3.10 -m venv .venv-test
.venv-test/bin/python -m pip install -r requirements-test.txt
PYTHONPATH=src .venv-test/bin/python -m pytest -q
```

Browser tests need Chromium, installed with
`.venv-test/bin/python -m playwright install chromium` (Linux may also require
`install-deps chromium`). The production installer installs the full visible
browser; model-free tests may additionally require Playwright's headless shell.
Use `bash -n setup.sh launch.sh launch-whiteboard.sh status.sh stop.sh` for shell syntax.

## Whiteboard build

Bundled assets let the Jetson run without Node. To rebuild on a development host
with Node22/npm10:

```bash
cd frontend/whiteboard
npm ci
npm run build
```

This regenerates static/whiteboard, local fonts, notices and the asset manifest.
Review and commit the matching manifest and assets together; preserve licenses.

## Real-device acceptance

Model-free tests prove invariants, not task success. On the supported Jetson, check
actual CUDA, fresh observations, at least two distinct goals/states, independent
verification, cancellation and exports. Retain failures and timing boundaries.
Document cold vs warm state and browser/profile reuse. A task must not be called
successful just because a model returned DONE or a file exists.

Do not commit models, wheels, caches, private evidence, screenshots, videos, PID
files, .env or config.local.json. Redact issue attachments. Read SECURITY.md before
reporting a security issue. Contributions are licensed under Apache-2.0.
