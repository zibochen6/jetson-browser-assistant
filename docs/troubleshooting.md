# Troubleshooting

## Installation stopped

Read the failed stage and rerun `./setup.sh` after fixing it. The installer does
not erase models or records. Use `./setup.sh --check` for a read-only host check.
A Mac/x86 failure is expected: run deployment on the Jetson.

For wheel download errors, follow the [fallback](installation.md#pytorch-download-fallback).
A checksum mismatch is a hard failure. Do not disable validation or rename an
unrelated wheel to the expected filename.

If CUDA is missing, check the JetPack image, /usr/local/cuda-12.6/bin/nvcc and the
matching torch wheel. Setup does not upgrade JetPack. `jetson-browser doctor`
checks actual CUDA computation, not merely the presence of a package name.

## X11 desktop

Log into the physical Jetson desktop with an X11 session. Running over SSH does
not create a desktop. Do not use `xhost +` to work around authentication.

From a terminal inside that desktop, check:

```bash
printf '%s\n' "$DISPLAY" "$XAUTHORITY" "$XDG_RUNTIME_DIR"
xprop -root _NET_WORKAREA
```

When using SSH, export the corresponding values from that same user's desktop;
never copy a different user's authority. The runtime inherits explicit values and
otherwise checks /run/user/<current UID>/gdm/Xauthority and ~/.Xauthority. A
Wayland-only session is outside the validated display path.

## Port occupied / another checkout

Run `./status.sh` in the checkout that started the models. Ports8790–8793 are fixed.
Finish/cancel work and run `./stop.sh` there before starting another checkout.
No unrelated process is killed. Deleting a PID file does not free a listening port.

## Model startup / memory

Inspect logs/laya.log and logs/qwen.log. Startup is separate from task timing.
The two models and browsers share the Jetson's 16GB memory. Close unused tabs/flow
windows, inspect free -h and swap, and retry after explicit project shutdown.
Do not change weights or MTP settings during an active task.

Unexpected model exits do not prove OOM without kernel evidence. Keep the logs,
version and memory samples when reporting a problem. Do not publish credentials,
private browser profiles or unredacted run artifacts.

## Browser closed / task awaiting input

A browser closed at idle reopens for the next task. A flight browser closed during
execution stops that task; don't replay old actions against a stale page. Use
status and the printed task ID to resume a clarification or cancel a pending task.
For a restarted whiteboard service, reopen the saved .excalidraw and submit anew.

A date in an example may have expired. Use YYYY-MM-DD in the future. Website layout,
network delays, login and real ticket availability can cause failure; no simulator
replaces the real result. Supported limits are documented in README/usage.
