# Complete Docker delivery on Jetson

The `laya-browser` case in jetson-examples distributes a complete ARM64 image:
application, pinned Qwen/Laya weights, CUDA Python dependencies, Chromium, local
whiteboard/fonts and CUDA llama.cpp. User machines do not compile or download
model files when starting the application.

Use the [case entrypoint](https://github.com/zibochen6/jetson-examples/tree/main/reComputer/scripts/laya-browser)
for launch commands, supported host baseline and actual release acceptance. Before
the case is merged/published, install that source checkout with `pip3 install .`.
The existing native installation remains available separately.

## Build on the ARM64 Jetson

```bash
bash docker/build.sh
```

To stage exact artifacts from an existing deployment, verifying sizes/checksums:

```bash
bash docker/build.sh --artifacts /absolute/path/to/existing-deployment
```

Only model files, the pinned torch/uv wheels, Chromium archive and llama.cpp source
are reused. The virtual environment, browser profile, logs and private task
records are never copied. Missing artifacts are downloaded from their pinned
sources before the build. `docker/prepare.py --verify-only` validates baked models.

The default image is
`chenduola6/jetson-laya-browser:0.1.0-rc1-jp62-r36.4.3-arm64`.
Set `JETSON_LAYA_IMAGE` to build under a different repository; this does not publish
it. The base is NVIDIA L4T JetPack r36.4.0; the delivery target is Orin NX16GB /
host L4T36.4.3 and requires its own GPU/desktop validation.

## Runtime layout

The Compose launcher uses NVIDIA Runtime, host user UID/GID, a read-only container
root, a writable `/data` mount and a dedicated Xauthority cookie. Application/model
links in `/data` point at immutable `/opt/jetson-browser` content. The existing
`JETSON_BROWSER_ROOT` setting keeps records/process ownership scoped to `/data`.
No source checkout is mounted from the host. Internal8790–8793 ports are not
published. `tini` reaps children; the controller starts models and the flight
service, checks health and stops owned services on container termination.

The controller allows one interactive terminal at a time. `exit` leaves models
resident; the example's clean command stops/removes the container and retains data.
Old in-progress tasks are marked interrupted on service restart, never replayed.

Image digests and IDs must be written to the case's `release.json` only after
validation. A Docker save/load archive may lose registry-digest metadata; the
launcher accepts the exact tested image ID without contacting the registry.

## Release evidence

Record image content ID, registry digest, source revision, base digest, model
manifests, image/pull/archive sizes, Docker/L4T versions and raw task results.
Run the model-free suite and actual container GPU/desktop/task checks. Publish the
validated image, export with `docker save`, and checksum the archive. Update
third-party distribution notices alongside dependency changes.

The animations in the case are reused unchanged from the existing Seeed Wiki.
They demonstrate application behavior; they are not new Docker benchmark recordings.
