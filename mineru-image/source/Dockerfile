# Source carrier image: packages MinerU source only (no Python deps installed here).
#
# MUST build from repository root:
#   docker build -t mineru-source:v2.7.4-fix -f mineru-image/source/Dockerfile .

FROM alpine:3.20

COPY . /src
RUN test -f /src/pyproject.toml || ( \
        echo "ERROR: /src/pyproject.toml not found." >&2; \
        echo "Build this image from the MinerU repository root, e.g.:" >&2; \
        echo "  docker build -t mineru-source:TAG -f mineru-image/source/Dockerfile ." >&2; \
        ls -la /src >&2; \
        exit 1 \
    )

WORKDIR /src
