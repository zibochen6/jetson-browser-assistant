# English demo guide

For the separate whiteboard demonstration (create → modify → recover after a
manual drag), use [the whiteboard guide](whiteboard.md). Run `./launch-whiteboard.sh`;
record the visible board yourself. Stop only the whiteboard scene before returning
to this flight demonstration: `.venv/bin/jetson-browser whiteboard stop`.

Use the existing Jetson X11 desktop and an English terminal font such as DejaVu Sans Mono. The program does not change the desktop language or start your screen recorder.

1. Open a terminal on the Jetson and run:

   ```bash
   cd /path/to/jetson-browser-assistant
   ./launch.sh
   ```

2. Wait for `Live flow ready`, `Models ready` and `Task>`. The website window is on the left and the Live Flow window is on the right. Model and window preparation is outside task timing; the actual Trip.com navigation begins after task submission. Start your own screen recorder now. No recording is started by the launcher.
3. Enter a task, then press Enter:

   ```text
   Find one-way flights from Shenzhen to Shanghai on 2026-11-13 for 1 adult in economy. Nonstop only, lowest price first. Show up to 3 options and open the fare options for one matching flight.
   ```

4. Watch `Elapsed`, the English progress messages and the active flow node. The timer includes parsing, inference, any required browser reopening, website waits, browser actions and final record saving. If you manually handle a login or verification prompt, that waiting time is included and also reported separately. Calendar-adapter actions are labelled separately from Laya model decisions.
5. Check `Status`, the verified route and date, actual candidates, and `Fare options opened`. Opening fare options does not create an order or make a payment.
6. Record the final `Task elapsed time (excluding model loading)`. Each task has a separate run ID and directory. The session then returns to `Task>` with the models resident and browser retained.
7. Submit another task, or type `exit`/`quit` to leave. Ctrl+C during execution cancels the current task; Ctrl+C/Ctrl+D at the idle prompt leaves the session.

After a task, select `Replay` in the flow window. Use Play/Pause, the timeline and 1×/2×/4× speed to record your own explanation. The real website stays where the task left it; replay does not repeat clicks. `Follow live` returns to automatic tracking of new tasks. Candidate actions are available under `Decision details`. Model reasoning is not generated for the display.

Use Up/Down to recall tasks from this terminal session. If the browser was closed while idle, the next task reopens it automatically. Closing the browser during a task stops execution without replaying actions; submit a new task to restart the query. After updating the software, exit the old terminal session and run `./launch.sh` again.

Another example:

```text
Find one-way flights from Guangzhou to Beijing on 2026-11-20 for 1 adult in economy. Nonstop only, lowest price first. Show up to 3 options and open the fare options for one matching flight.
```

Use an unambiguous future date in `YYYY-MM-DD` format. Prices change; report only what the current website shows. Do not describe inspected options as the global cheapest flights. Chinese input remains compatible, but all new demo tasks should use English.

The launcher is equivalent to `jetson-browser run --loop --keep-open --no-video --visualize`. Add `--no-visualize` for terminal-only use. Run `.venv/bin/jetson-browser visualize` to open the flow separately while idle. Single-task commands, `start`, `stop`, `resume`, and `cancel` still work. If the environment is missing, follow the setup instructions first; the launcher does not reinstall dependencies or change JetPack.
