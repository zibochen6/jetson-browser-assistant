# Usage

[Install first](installation.md), then run the launchers on the Jetson X11 desktop.
All generated prompts and demo requests use English. Flight dates use YYYY-MM-DD;
replace old example dates with future dates. Model loading happens before Task>.

## Flights

```bash
./launch.sh
./launch.sh --no-visualize
```

These enter a continuous loop, keep the browser and disable video. Submit tasks
one at a time. The first example in the README asks for fare options; that means
opening and verifying Select Fare, not submitting a booking. Check Query verified,
Fare options opened and the returned actual candidates.

Single task without the flow window:

```bash
.venv/bin/jetson-browser run "Find one-way flights from Shenzhen to Shanghai on 2026-11-13 for 1 adult in economy, nonstop only, lowest price first." --keep-open --no-video
```

`--query-only` skips opening fare options. Login/captcha prompts are handled by a
person, not bypassed. A user-waiting task blocks other submissions until resumed
or cancelled. Inspect service health with `./status.sh`.

```bash
.venv/bin/jetson-browser resume TASK_ID
.venv/bin/jetson-browser cancel TASK_ID
```

When the browser was closed while idle, a new task reopens its profile. Closing it
during a flight task stops that task without replaying actions. After a service
restart, old records remain readable; a stale task is not automatically re-executed.

## Whiteboard

```bash
./launch-whiteboard.sh
./launch-whiteboard.sh --open examples/whiteboard/blank.excalidraw
```

The second command replaces the current canvas. Do not use it between successive
edits you want to preserve. Use explicit, unique labels. Short commands work best:

```text
Make Jetson green. Keep everything else.
Rename Display to Monitor. Keep everything else.
Delete Robot Arm. Keep everything else.
```

Submit each line separately. A deleted box also loses its incident arrows through
actual UI operations. Complex deletion/keep clauses may need clarification rather
than being guessed. Rectangles support transparent/red/green/blue/yellow backgrounds;
standalone text supports black/red/green/blue/orange. Arbitrary shapes, rotation,
dense imported canvases and off-grid layouts are outside the validated scope.

After the task finishes, manual UI changes are read again for the next instruction.
For the tested manual-drag recovery sequence and editable exports, see
[the whiteboard guide](whiteboard.md).

```bash
.venv/bin/jetson-browser whiteboard resume RUN_ID
.venv/bin/jetson-browser whiteboard cancel RUN_ID
./launch-whiteboard.sh --open whiteboard-runs/RUN_ID/scene.excalidraw
```

`resume` handles clarification in the current service session. After a service
restart, reopen the saved scene and submit a new instruction. `Open scene` uses the
real file input. Per-task exports are checkpoints; browser autosave also preserves
idle edits.

## Timing, cancellation and exit

Pressing Enter on a valid task starts its independent timer. Model preload,
startup warmup and input waiting are excluded. Parsing, required navigation,
inference, UI input, waits, independent verification and saving are included.
Explicit `--open` preparation happens before the prompt. Human waiting is included
in total and separately reported. Nested span timings can overlap; don't sum them.

- Ctrl+C during a task cancels it and returns to Task>. Whiteboard cleanup releases
  mouse/modifier keys and preserves the available scene and records.
- `exit`, `quit`, idle Ctrl+C or Ctrl+D exits the terminal only. Models/windows
  remain resident. A new task gets a new run ID even when using the same canvas.
- `./stop.sh` stops whiteboard, flow, flight service and shared models. This is an
  explicit shutdown, so finish tasks or cancel them first.
- `.venv/bin/jetson-browser whiteboard stop` stops only the whiteboard service/window.

## Artifacts and replay

Flights: `runs/RUN_ID/`; whiteboard: `whiteboard-runs/RUN_ID/`. Look at result.json,
events.jsonl, actual observations and final screenshots. Whiteboard adds
verification.json, scene.excalidraw and canvas.png. Failed/cancelled tasks retain
available evidence and an actual reason; an absent export is not success.

Flight Live Flow follows actual service events. Replay changes the flow display
only; it does not click the website or reconstruct historical website images.
See [Live Flow](live-flow.md). No generated model reasoning is shown.
