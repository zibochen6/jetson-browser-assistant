# Live Flow and event replay

On the Jetson desktop, run `./launch.sh`. It preloads the existing local models and opens the actual website window on the left and a separate presentation browser on the right. The layout uses the X11 work area without changing the display resolution. Enter your task at `Task>` as before. Window preparation happens before task input; Trip.com navigation and all subsequent task work remain within task timing.

The presentation is read-only. It polls actual task state and incremental events every 0.5 seconds. It makes no model requests, captures no periodic screenshots, loads no external CDN and starts no video recording. The site and flow use separate persistent profiles; flow controls are never offered to Laya as website actions. Closing the flow has no effect on the execution service.

## What the flow shows

- **Qwen:** request parsing, field text generation and the single recovery decision when used.
- **Laya:** the actual offered actions and returned selection. Expand Decision details to inspect them.
- **Browser tool:** page observation, navigation and actual browser interactions.
- **Executor guard / program verifier:** permission checks, stale-target checks, search conditions, result query, sort state and matching fare options.
- **Calendar adapter:** exact-date selection and readback; these actions are not attributed to Laya.
- **Website wait:** action postconditions and stable result readiness. A highlighted waiting node does not mean the model is still deciding.

Short operations can finish between two polls; their recorded visits and durations remain visible, and replay follows their timestamps. The flow does not hold a node artificially to slow the task. Event transitions use short, non-looping motion and respect reduced-motion settings.

Node times measure operation wall time. A Laya request includes local HTTP overhead; the terminal's Laya metric uses the model server's inference measurement. Nested operations, such as a calendar adapter observing and clicking dates, overlap. Do not add every node duration to reconstruct total task time.

## Live and Replay

Live follows each new task automatically. Task time freezes at completion. Human waiting, blocked execution, cancellation and failures are displayed as recorded; they are never presented as successful completion. A disconnected service is explicitly labelled Disconnected.

Replay provides a run selector, Play/Pause, a draggable timeline and 1×/2×/4× playback. It replays events only: the actual Trip.com window does not change, and no website action is executed. Query and fare verification appear only when reached in the recorded timeline. Follow live returns to new tasks without changing the task itself.

Earlier records remain unchanged. Their event timestamps are supported, but missing operation start times are labelled Not recorded rather than reconstructed as precise operation durations. Historical events remain available after execution-service restarts.

## Commands and local interfaces

```bash
./launch.sh                         # Models, website, Live Flow, then Task>
./launch.sh --no-visualize          # Close Live Flow and use the terminal-only layout
.venv/bin/jetson-browser visualize # Open/reuse Live Flow while idle; submit no task
.venv/bin/jetson-browser stop      # Stop this project's presentation and services
```

The flow is served at `http://127.0.0.1:8790/visualizer`. Its GET-only data sources are `/health`, `/runs?limit=20`, `/tasks/{id}` and `/tasks/{id}/events?after=0`. Existing event pagination is preserved. `/health` adds `latest_task_id`; new records include relative event times and paired operation IDs. The CLI uses `POST /presentation` solely to arrange windows while idle; it is not called by the presentation page and cannot change query fields or execute website actions. All services remain on loopback.

Source assets ship inside the Python package and require no frontend build tool. The presentation browser is managed independently under `runtime/visualizer-profile`; normal website state stays in `profile/`. Recorded task evidence stays in `runs/`.

See [target-board validation](validation-summary.md) for real task results, lifecycle checks and memory observations.
