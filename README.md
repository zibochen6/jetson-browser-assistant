# Jetson Browser Assistant

Run a **local decision model + local text model** on a Jetson to operate a real
browser or edit a whiteboard through mouse and keyboard input.

[简体中文](README.zh-CN.md) · [Installation](docs/installation.md) ·
[Usage](docs/usage.md) · [Troubleshooting](docs/troubleshooting.md)

| Demo | What you can ask it to do | What it saves |
| --- | --- | --- |
| Flight assistant | Search Trip.com, verify the route/date, filter nonstop flights, sort by price and open fare options | Real candidates, query evidence, screenshots and per-task events |
| Whiteboard assistant | Create labeled boxes/arrows, recolor, rename, move and delete objects on the same canvas | Editable `.excalidraw`, PNG, screenshot and independent verification |

**Qwen parses the request and generates text. Laya selects an operation/target from
current legal candidates. Playwright executes it. The program independently checks
the actual result.** Tools, site adapters and layout rules are implemented in code;
this is a bounded assistant, not a general-purpose visual computer-use model.

Model inference is local. Trip.com requires internet access; the whiteboard and its
fonts are served locally after installation. No recording starts automatically.

## Quick start on Jetson

Validated hardware: **reComputer Industrial J4012 / Jetson Orin NX 16GB**.
Use an Ubuntu 22.04 JetPack 6.1/6.2 image with L4T R36.4.x, **CUDA 12.6** and
system **Python 3.10**. A logged-in **X11 desktop**, display and at least 20 GiB free
disk space are recommended. Lower-memory Jetsons, other CUDA versions, macOS and
x86 are not supported deployment targets for this release.

```bash
git clone https://github.com/zibochen6/jetson-browser-assistant.git
cd jetson-browser-assistant
./setup.sh
```

Run setup **as your desktop user**, without `sudo`. It requests sudo only for system
libraries. The installer checks the device, downloads/checks the ARM64 PyTorch wheel,
creates an isolated uv environment, installs Chromium, downloads pinned model files,
builds CUDA llama.cpp, checks CUDA and preloads the services. It does not flash
JetPack, upgrade system Python or change the desktop resolution/language.

Downloads/builds can take a while. Rerun the same command after an interruption;
verified downloads and the existing build are reused. If the Seeed download host
is unavailable, use the [local wheel fallback](docs/installation.md#pytorch-download-fallback).

### Try the whiteboard first

```bash
./launch-whiteboard.sh --open examples/whiteboard/blank.excalidraw
```

`--open` replaces the current canvas; existing exports remain. Wait for
`Models ready` and `Task>`, then paste the following **task text**, without `Task>`:

```text
Draw three labeled boxes: Camera on the left, Jetson in the center, and Display on the right. Connect Camera to Jetson and Jetson to Display with arrows.
```

After completion, submit another task on the same canvas:

```text
Make Jetson green. Add a box labeled Robot Arm below Jetson and connect Jetson to Robot Arm. Keep everything else.
```

To keep the existing canvas on your next launch, use `./launch-whiteboard.sh`
without `--open`. See [all whiteboard controls and supported edits](docs/whiteboard.md).

### Try the flight assistant

Finish or cancel any active whiteboard task first. Stop just its scene if desired:

```bash
.venv/bin/jetson-browser whiteboard stop
./launch.sh
```

Enter an English request. Replace the date with a valid future `YYYY-MM-DD` date:

```text
Find one-way flights from Shenzhen to Shanghai on 2026-11-13 for 1 adult in economy. Nonstop only, lowest price first. Show up to 3 options and open the fare options for one matching flight.
```

The default launcher shows a website window and a read-only Live Flow. Use
`./launch.sh --no-visualize` for just the website. It opens fare options, never
submits an order or payment. Prices and website availability can change.

## Everyday controls

| Action | Command / input |
| --- | --- |
| Install or repair the deployment | `./setup.sh` |
| Check the host without installing anything | `./setup.sh --check` |
| Open flights / whiteboard | `./launch.sh` / `./launch-whiteboard.sh` |
| Inspect services without loading models | `./status.sh` |
| Cancel the current task | Ctrl+C during execution; returns to `Task>` |
| Leave the terminal, keep models/browser resident | `exit` or `quit` at `Task>`; idle Ctrl+C/Ctrl+D also work |
| Stop the whiteboard only | `.venv/bin/jetson-browser whiteboard stop` |
| Stop all project services/models and both scenes | `./stop.sh` |

Timing starts when you press Enter to submit the task. Model loading, startup
warmup and input waiting are excluded; parsing, required browser startup, model
calls, UI, waits, checks and artifact saving are included. Human waiting is included
and also shown separately. Each task has its own run ID and a frozen final time.

Records are private local files in `runs/` (flights) or `whiteboard-runs/` (board).
Do not commit profiles, raw run records or screenshots containing personal data.
[Usage](docs/usage.md) covers resume, cancellation, re-opening exports and updates.

## What this release does and does not establish

- Real Jetson checks cover a limited Trip.com task family and small rectangle/text/
  arrow whiteboards. A verifier, stale-target checks, bounded retries and task
  budgets remain necessary even with constrained model choices.
- Laya sees text state and candidates, not screenshots. The adapter computes
  geometry and performs bounded UI gestures. Model `DONE` does not prove success.
- No claim of being faster or cheaper to maintain than a deterministic script:
  no equivalent script baseline has been measured.
- Historical checks include 9/10 held-out flight queries on an earlier version and
  same-canvas creation/modification/recovery. These are not a general website
  success rate or a promised task latency. See [validation](docs/validation-summary.md).
- 16GB is shared CPU/GPU memory. Browsers, other processes and swap affect results;
  close unused windows and monitor long-running sessions.
- No voice input, mid-action goal changes, arbitrary drawing, collaboration or
  unattended purchasing. Login/verification prompts require a person.

## Pinned components

| Component | Release configuration |
| --- | --- |
| Laya | `cklxx/laya-browser` v19s, revision `645cf366a2ae35f1086e8c20eff48f909bb49206`; original wrapper, CUDA, `fast=False` |
| Text model | `unsloth/Qwen3.5-4B-MTP-GGUF`, revision `86835bf9949e4d14d6860f7910b1340ad4f271a9`; Q4_K_M |
| llama.cpp | `785322d17f2d51e5185cf996a1f4e46d87640841`, CUDA sm_87; context8192, one slot, thinking off, MTP depth2 |
| Python | System3.10, uv0.13.6, torch2.7.0 CUDA12.6, laya0.3.9, transformers4.57.6 |
| Browser | Playwright1.64.1 / ARM64 Chromium156.0.8078.4 |
| Whiteboard | Excalidraw0.18.1, React18.3.1; bundled static assets and local fonts |

`uv.lock`, model manifests and `artifacts.lock.json` pin dependencies and downloads.
The wheel checksum records the verified deployment artifact, not an upstream
signature. Model weights are downloaded separately and are not committed here.

## Configuration and development

Create an ignored `config.local.json` to override supported defaults without editing
the tracked configuration. For example:

```json
{
  "max_actions": 40,
  "timeout_seconds": 600,
  "record_video": false
}
```

This release uses fixed loopback ports: flights8790, Laya8791, Qwen8792,
whiteboard8793. Do not expose them through a public reverse proxy; they are local
control APIs without authentication. A second checkout refuses occupied ports
rather than reusing/stopping an unrelated process. Custom service ports are not
supported. Desktop environment variables are inherited; see [X11 help](docs/troubleshooting.md#x11-desktop).

[Architecture](docs/architecture.md) explains the adapters and decision loop.
[Contributing](CONTRIBUTING.md) includes model-free tests and frontend rebuilds.
Model-free CI does not replace real Jetson acceptance. See the [public packaging checks](docs/release-validation.md) for exactly what was tested.

## Hardware and licensing

The measured platform is [reComputer Industrial J4012](https://www.seeedstudio.com/reComputer-Industrial-J4012-p-5684.html).
[Seeed's getting-started guide](https://wiki.seeedstudio.com/reComputer_Industrial_Getting_Started/)
covers the device; [the PyTorch guide](https://github.com/Seeed-Projects/reComputer-Jetson-for-Beginners/tree/main/3-Basic-Tools-and-Getting-Started/3.5-Pytorch)
provides the matching wheel. Other products require their own compatibility check.

Project code: [Apache-2.0](LICENSE). Third-party components and models retain their
own licenses; see [NOTICE](NOTICE) and [THIRD_PARTY.md](THIRD_PARTY.md).
This project is not an official NVIDIA, Qwen, Trip.com or Excalidraw product.
