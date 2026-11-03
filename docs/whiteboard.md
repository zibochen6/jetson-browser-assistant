# Local whiteboard assistant

This scene uses the existing Qwen3.5-4B and Laya v19s CUDA services. It edits an
embedded, fully local Excalidraw 0.18.1 board through real UI input. No automatic
screen recording is started. The flight launcher remains available separately.

## Launch on the Jetson desktop

```bash
cd /path/to/jetson-browser-assistant
./launch-whiteboard.sh
```

Wait for `Models ready` and `Task>`. Enter an English task and press Enter.
The visible board opens on the first task and the same board is reused afterwards.
Loading, startup warmup and input waiting are outside task timing. Parsing,
necessary browser opening, model calls, UI input, waits, verification and exports
are included. Human waiting is included in the total and also reported separately.
Each task gets its own run ID and frozen final duration. Model health is checked
before each Task>; a stopped model is restored before timing starts.

For a repeatable demonstration starting from an empty board, explicitly open the
provided blank file before submitting the first task:

```bash
./launch-whiteboard.sh --open examples/whiteboard/blank.excalidraw
```

Opening this file replaces the current canvas. Existing task exports remain in
`whiteboard-runs/`. Do not open it between the following three tasks.
Explicit `--open` preparation happens before `Task>` and is excluded from the
subsequent task timer. Without it, the first required browser opening is timed.

### A — create

```text
Draw three labeled boxes: Camera on the left, Jetson in the center, and Display on the right. Connect Camera to Jetson and Jetson to Display with arrows.
```

### B — modify the same canvas

```text
Make Jetson green. Add a box labeled Robot Arm below Jetson and connect Jetson to Robot Arm. Keep everything else.
```

### C — recover after a manual change

After B finishes and the terminal returns to `Task>`, select the Selection tool
(shortcut V), then drag Camera to an empty area near the lower right of the board.
Do not edit the Agent's records. Enter:

```text
Move Camera back to the left of Jetson and tidy the layout. Keep all labels, colors, and connections.
```

Additional supported examples:

```text
Rename Display to Monitor. Keep everything else.
Delete Robot Arm. Keep everything else.
Add text labeled Edge AI below Camera. Make Edge AI blue. Keep everything else.
```

Use an explicit label for each edited object. `Delete Robot Arm` also removes its
incident arrows through actual UI input. Prefer one clear delete clause; complex
sentences mixing arrow deletion, endpoints and keep clauses can require clarification.

## Recording layout and controls

The board has a fixed 1440 × 1000 browser CSS viewport and 100% initial canvas zoom.
Its native window is positioned with room for desktop/Chromium borders; the system
resolution is unchanged. The main area is the canvas. The top strip shows the
last received status, elapsed time and operation counts. `Run details` is collapsed
by default. A manual edit after completion is labeled as a canvas change, rather
than claiming that the changed board is still verified.

Choose this browser window in your own screen recorder; keep the terminal nearby
if you want to show task input. The launcher does not start a recorder or create
video files. Existing flight windows can be minimized or closed by the user. On a
16GB device, avoid keeping an unused Live Flow window and extra browsers open.

- Ctrl+C while running: cancel the current task, release mouse/modifier keys, save
  available evidence, then return to `Task>`.
- `exit`, `quit`, Ctrl+C or Ctrl+D at the idle prompt: leave the terminal session;
  shared models and the board service stay available.
- The frontend autosaves the scene locally after UI changes. Browser reopening
  restores it. Per-task exported files are the explicit recovery checkpoints.

```bash
.venv/bin/jetson-browser whiteboard resume RUN_ID
.venv/bin/jetson-browser whiteboard cancel RUN_ID
.venv/bin/jetson-browser whiteboard stop
./launch-whiteboard.sh --open whiteboard-runs/RUN_ID/scene.excalidraw
```

`resume` handles a task waiting for clarification. After an execution-service
restart, old tasks are not automatically resumed. Open a saved scene and submit a
new instruction. `stop` closes only the whiteboard-owned service and browser;
shared models, flight service and flight profile are retained.

Return to the flight demonstration:

```bash
.venv/bin/jetson-browser whiteboard stop
./launch.sh
```

## What the models and program actually do

1. Read the current public Excalidraw scene, including object IDs, bound labels,
   coordinates, colors, selection and arrow bindings.
2. Qwen returns structured requested changes. The program resolves identities,
   validates explicit targets/deletions/keep constraints and computes grid positions.
3. Offer multiple currently legal edit capabilities to Laya, such as creating a
   missing box, choosing a color, selecting an object or connecting two boxes.
4. Resolve Laya's offered action ID and check that the observed scene revision is
   still current. A changed board causes re-observation, not a stale click.
5. Execute the chosen capability through toolbar/property clicks, real mouse
   gestures, text input and shortcuts. A create-box capability is a bounded UI
   sequence: choose Rectangle, drag, edit its bound label. Low-level inputs are
   logged separately from model-selected logical operations.
   Each drag or double-click is one input operation; interpolated mouse events
   are not presented as separate decisions or inflated action counts.
6. Read the actual scene again. Independently check labels, colors, positions,
   arrow direction/bindings, existing identities and preserved content. `DONE`
   from a model is insufficient. Already-satisfied tasks may need zero Laya calls.
7. Export the actual scene, PNG and viewport screenshot. Reject an export snapshot
   if the canvas changes while saving.

Laya is **not** given screenshots and does not generate free-form coordinates or
reasoning text. Its original v5 wrapper is retained. Canvas capabilities are
explicitly marked in the request as executor capabilities encoded as CLICK target
choices, rather than pretending they are DOM buttons. Geometry/layout and the
low-level UI sequence belong to the adapter. There is no predetermined global
operation order or single-correct-action candidate list.

The complete action history is retained in the records. Completed whiteboard
macros are omitted from Laya's navigation-history context: actual target experiments
showed they could trigger premature DONE. The model still sees fresh scene facts,
all unmet constraints, legal choices and recent unsuccessful operations. There is
at most one Qwen correction/recovery per task in addition to normal parsing;
clarification from the user can trigger a new parse.

The integration exposes public scene reads and exports only. Drawing/editing never
uses `updateScene`, `setActiveTool` or equivalent scene writes. `Open scene` uses a
real file input, the public `loadFromBlob` helper and component initialization.
File import is an explicit user operation, not a shortcut for generating a diagram.

## Records and interfaces

Every `whiteboard-runs/RUN_ID/` contains the original goal in `result.json`, parsed
`task.json`, the compiled contract, fresh before/after scene observations,
`events.jsonl` with model requests/responses and UI receipts, independent
`verification.json`, `final-scene.json`, `scene.excalidraw`, `canvas.png`,
`screenshot.png` and 0.5s `memory.jsonl` samples. Failed/cancelled tasks retain
available artifacts and reasons. Per-operation autosaves are also retained.

Timing counters use actual operation spans, including interrupted requests.
Nested observation/wait spans can overlap and should not be added as a complete
partition of total time.

Memory figures are **whole-system** shared CPU/GPU memory (`MemTotal -
MemAvailable`) and swap from `/proc/meminfo`, not dedicated GPU memory or the
incremental cost of this scene. Other open programs affect them.

The service binds only to `127.0.0.1:8793`. The display polls health/status using
GET only. It does not call models, take periodic screenshots or execute actions.

| Interface | Purpose |
| --- | --- |
| GET `/whiteboard/` | Bundled local application and fonts |
| GET `/health` | Service identity, active/latest task and browser state |
| GET `/board` | Fresh public scene read |
| GET `/tasks/ID` and `/tasks/ID/events?after=N` | State and paginated records, including disk archives |
| POST `/tasks` | CLI task submission |
| POST `/tasks/ID/resume`, `/tasks/ID/cancel` | Explicit CLI control |
| POST `/open` | Explicit idle-only file import |

Assets are pinned/checksummed in `manifest-whiteboard-assets.json`. The runtime
requires no Node/npm or CDN. To rebuild on the development Mac:

```bash
cd frontend/whiteboard
npm ci --no-audit --no-fund
npm run build
```

After updating application code, run `jetson-browser whiteboard stop` once before
relaunching, so the service imports the updated code. Do not upgrade JetPack,
global Python, PyTorch or model weights for this scene.

## Limits

First version: English instructions with explicit unique labels; at most 12
objects in the supported grid area; unrotated rectangles, text and rectangle-bound
arrows; a fixed viewport/view. Default active budget is 600 seconds / 80 logical UI
operations, with three unchanged-operation detection, two local/stale retries and
one Qwen recovery. Final verification and saving run after stopping UI execution.
Rectangle backgrounds support transparent/red/green/blue/yellow. Standalone text
uses the native black/red/green/blue/orange palette; unsupported text yellow is
rejected rather than silently substituted with orange.

This is a bounded diagram-editing assistant, not arbitrary drawing, an image-based
spatial agent, a universal editor, or proof of general Laya drawing ability.
Ambiguous/contradictory plans are rejected or request clarification. No guarantee
is made for arbitrary English or Chinese expressions, dense/overlapping/imported
complex boards, user input during an active gesture, freehand, collaboration or
voice control. Current acceptance and known failure examples are in
[whiteboard-validation.md](validation-summary.md).
