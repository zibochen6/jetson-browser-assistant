# Build on an ARM64 Jetson. docker/prepare.py stages and verifies build inputs.
ARG BASE_IMAGE=nvcr.io/nvidia/l4t-jetpack:r36.4.0@sha256:34ccf0f3b63c6da9eee45f2e79de9bf7fdf3beda9abfd72bbf285ae9d40bb673
FROM ${BASE_IMAGE}
ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.title="Jetson Browser Assistant" \
      org.opencontainers.image.source="https://github.com/zibochen6/jetson-browser-assistant" \
      org.opencontainers.image.revision=${SOURCE_REVISION} \
      org.opencontainers.image.licenses="Apache-2.0"
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics,display \
    PATH=/opt/jetson-browser/.venv/bin:/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PLAYWRIGHT_BROWSERS_PATH=/opt/chromium HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    JETSON_BROWSER_ROOT=/data JETSON_BROWSER_CONTAINER=1 JETSON_DEVICE_MODEL_PATH=/run/jetson/model \
    HOME=/data/home XDG_CACHE_HOME=/data/cache XDG_RUNTIME_DIR=/data/xdg TERM=xterm-256color
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-venv ca-certificates curl git build-essential cmake ninja-build \
    pkg-config libcurl4-openssl-dev libopenblas-dev libopenmpi-dev libomp-dev \
    xterm fonts-noto-cjk unzip x11-utils x11-xserver-utils tini \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libx11-6 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libdrm2 \
    libxcb1 libxkbcommon0 libcups2 libdbus-1-3 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/jetson-browser
COPY pyproject.toml uv.lock artifacts.lock.json config.json manifest-*.json LICENSE NOTICE THIRD_PARTY.md ./
COPY src/ src/
COPY scripts/ scripts/
COPY examples/ examples/
COPY vendor/wheels/ vendor/wheels/
COPY runtime/llama-source.tar.gz runtime/chromium-linux-arm64-1248.zip runtime/
RUN python3 scripts/verify_artifact.py torch vendor/wheels/torch-2.7.0-cp310-cp310-linux_aarch64.whl \
    && JETSON_OFFLINE=1 python3 scripts/bootstrap_uv.py \
    && runtime/tools/uv venv --python /usr/bin/python3.10 .venv \
    && runtime/tools/uv sync --frozen --no-dev \
    && .venv/bin/python scripts/install_browser.py \
    && bash scripts/build_llama.sh \
    && rm -rf vendor/wheels runtime/tools runtime/llama-source.tar.gz runtime/chromium-linux-arm64-1248.zip /root/.cache
COPY models/ models/
COPY docker/ docker/
RUN python3 docker/prepare.py --verify-only \
    && chmod -R a+rX /opt/jetson-browser /opt/chromium
WORKDIR /data
HEALTHCHECK --interval=10s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "/opt/jetson-browser/docker/runtime.py", "health"]
ENTRYPOINT ["/usr/bin/tini", "--", "python", "/opt/jetson-browser/docker/runtime.py"]
CMD ["serve"]
