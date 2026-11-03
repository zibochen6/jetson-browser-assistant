# Installation

Run on the Jetson itself, as the logged-in desktop user. The validated target is
Orin NX16GB / Ubuntu22.04 / L4T R36.4.x / CUDA12.6 / Python3.10. This installer
rejects incompatible hosts before installing anything. It does not flash JetPack
or configure an X server. See the [README](../README.md) for the first task.

## Default path

```bash
./setup.sh --check
./setup.sh
```

Six stages: host/system checks, pinned PyTorch, isolated uv environment, Chromium,
model files/CUDA build and service preload. `uv sync --frozen --no-dev` uses the
committed lock and never creates a new lock. uv is reused only at the pinned
version; otherwise it is installed in `runtime/tools`, not into system Python.
All commands work when the checkout path contains spaces.

Dependencies and model downloads require network access. Build/download duration
is outside task timing. Models execute repository-pinned wrapper code; inspect
that code and upstream licenses before running an untrusted fork.

## PyTorch download fallback

The installer uses the public download endpoint behind the PyTorch2.7 link in
[Seeed's guide](https://github.com/Seeed-Projects/reComputer-Jetson-for-Beginners/tree/main/3-Basic-Tools-and-Getting-Started/3.5-Pytorch).
It rejects HTML/error pages and checks the exact size and SHA256 in
`artifacts.lock.json`. The checksum identifies our deployment artifact, not an
upstream signature.

If the host blocks downloads, obtain the matching CUDA12.6 / cp310 / ARM64 wheel
on another computer, transfer it and run:

```bash
./setup.sh --torch-wheel /path/to/torch-2.7.0-cp310-cp310-linux_aarch64.whl
```

An alternate `--torch-url URL` is also supported with the **same** fixed checksum.
Never substitute a CPU wheel or a wheel for another Python/CUDA version.

## Existing systems and staged installs

```bash
./setup.sh --skip-system-deps --no-start
./setup.sh --environment-only --no-start
./setup.sh --jobs 2
```

`--skip-system-deps` assumes both the build libraries and Chromium's shared
libraries already exist; it makes no apt changes. `--no-start` does not start,
reuse, cancel or stop running model/browser services. `--environment-only` installs
Python/Chromium and checks CUDA, skipping model download, CUDA build and preload.
It cannot run a model task until full setup completes.

Services use fixed local ports8790–8793. A second checkout can be installed with
`--no-start`, but cannot launch while the original checkout owns those ports.
Use `./stop.sh` **in the owning checkout** before switching, after finishing tasks.
Never kill an unrelated process just to clear a port.

## Downloads and offline preparation

Downloads use `.partial` files and validate before replacing the final artifact.
After an interruption, repeat setup. If an HTTP server ignores Range requests,
the download safely restarts; incorrect range responses are rejected.

For restricted networks, stage the following from a matching installation:

- `vendor/wheels/torch-2.7.0-cp310-cp310-linux_aarch64.whl`;
- the pinned uv executable on PATH or the locked uv wheel under `vendor/wheels/`;
- uv's cached dependencies for this lock and platform;
- full `models/` from `python3 scripts/fetch_models.py` (the fetch script also runs on a Mac);
- Chromium's existing Playwright cache, or the pinned archive at
  `runtime/chromium-linux-arm64-1248.zip`;
- `runtime/llama-source.tar.gz`, or the same built `runtime/llama.cpp` and matching
  `runtime/llama-commit.txt` from compatible hardware/software.

With system libraries already installed:

```bash
./setup.sh --offline --no-start
```

Offline mode disables apt, uv network resolution and artifact/model/source
network requests. Missing cache entries fail with a repair message; this is not an
all-in-one offline distribution. Downloads remain separate from the source repo.

## Desktop and optional recording

Use the real X11 desktop. `DISPLAY`, `XAUTHORITY` and `XDG_RUNTIME_DIR` are inherited;
otherwise the runtime checks the current user's GDM authority and `.Xauthority`.
See [desktop troubleshooting](troubleshooting.md#x11-desktop).

Recording defaults to off. To intentionally enable legacy built-in flight video,
install its encoder (`.venv/bin/python -m playwright install ffmpeg`), set
`record_video` in `config.local.json`, then use a single-run CLI without
`--no-video`. `launch.sh` always disables built-in video; the whiteboard never
starts a recorder. Normal use saves screenshots and structured records.

## Update

Finish/cancel tasks, exit old terminal prompts, and stop project services before
updating:

```bash
./stop.sh
git pull --ff-only
./setup.sh
```

Keep `runs/`, `whiteboard-runs/`, `profile/`, `models/` and `config.local.json`.
Do not run `git clean -fdx`: it removes local models, sessions and task records.
