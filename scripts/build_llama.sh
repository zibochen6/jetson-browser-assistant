#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
COMMIT=785322d17f2d51e5185cf996a1f4e46d87640841
mkdir -p runtime
if test -x runtime/llama.cpp/build/bin/llama-server && test -f runtime/llama-commit.txt && test "$(cat runtime/llama-commit.txt)" = "$COMMIT"; then
  echo 'Pinned CUDA llama.cpp build already exists.'
  runtime/llama.cpp/build/bin/llama-server --version
  exit 0
fi
if ! test -f runtime/llama.cpp/CMakeLists.txt; then
  if ! tar -tzf runtime/llama-source.tar.gz >/dev/null 2>&1; then
    if test "${JETSON_OFFLINE:-0}" = 1; then
      echo 'Offline llama.cpp source missing: runtime/llama-source.tar.gz' >&2
      exit 1
    fi
    curl --fail --location --retry 3 "https://codeload.github.com/ggml-org/llama.cpp/tar.gz/$COMMIT" -o runtime/llama-source.tar.gz
  fi
  python3 scripts/verify_artifact.py llama_source runtime/llama-source.tar.gz
  mkdir -p runtime/llama.cpp
  tar -xzf runtime/llama-source.tar.gz -C runtime/llama.cpp --strip-components=1
fi
export PATH="/usr/local/cuda-12.6/bin:$PATH"
cmake -S runtime/llama.cpp -B runtime/llama.cpp/build -G Ninja -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 -DGGML_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF
cmake --build runtime/llama.cpp/build --target llama-server -j "${LLAMA_BUILD_JOBS:-4}"
runtime/llama.cpp/build/bin/llama-server --version
printf '%s\n' "$COMMIT" > runtime/llama-commit.txt
