# syntax=docker/dockerfile:1
# Runtime image: mount source from mineru-src image, uv install deps, keep official entrypoint.
#
# Build (after mineru-src:latest exists):
#   docker build -t mineru-runtime:latest -f mineru-image/runtime/Dockerfile .
#
# Or use: mineru-image/build.sh

# ARGs used in FROM must be declared before the first FROM.
ARG UV_VERSION=0.7.13
ARG SOURCE_IMAGE=mineru-src:latest

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv
FROM ${SOURCE_IMAGE} AS src

FROM vllm/vllm-openai:v0.10.1.1

# For Volta / Turing / Blackwell GPUs, use vllm/vllm-openai:v0.11.0 as base instead.

# Re-declare build args for this stage (FROM resets ARG scope).
ARG MINERU_EXTRAS=core
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        fontconfig \
        fonts-noto-cjk \
        fonts-noto-core \
        libgl1 && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /workspace

# Bind-mount source from carrier image for install only; source is not kept in final layers.
RUN --mount=type=bind,from=src,source=/src,target=/mnt/src,readonly \
    --mount=type=cache,target=/root/.cache/uv \
    sh -ec '\
      test -f /mnt/src/pyproject.toml || (echo "source image missing /src/pyproject.toml; rebuild mineru-source from repo root" >&2; ls -la /mnt/src >&2; exit 1); \
      cp -a /mnt/src /tmp/mineru-src; \
      uv pip install --system "/tmp/mineru-src[${MINERU_EXTRAS}]"; \
      rm -rf /tmp/mineru-src \
    '

ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
