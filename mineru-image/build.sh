#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

REGION="${1:-global}"
SOURCE_TAG="${SOURCE_TAG:-mineru-src:latest}"
RUNTIME_TAG="${RUNTIME_TAG:-mineru-runtime:latest}"
MODELS_TAG="${MODELS_TAG:-mineru-vllm:v2.7.4-fix}"
MINERU_EXTRAS="${MINERU_EXTRAS:-core}"

echo "[1/2] Building source carrier image: ${SOURCE_TAG}"
docker build -t "${SOURCE_TAG}" -f mineru-image/source/Dockerfile .

echo "[2/2] Building runtime image: ${RUNTIME_TAG} (extras=${MINERU_EXTRAS})"
if [[ "${REGION}" == "china" ]]; then
  docker build -t "${RUNTIME_TAG}" \
    --build-arg "SOURCE_IMAGE=${SOURCE_TAG}" \
    --build-arg "MODELS_IMAGE=${MODELS_TAG}" \
    --build-arg "MINERU_EXTRAS=${MINERU_EXTRAS}" \
    -f mineru-image/runtime/Dockerfile.china .
else
  docker build -t "${RUNTIME_TAG}" \
    --build-arg "SOURCE_IMAGE=${SOURCE_TAG}" \
    --build-arg "MINERU_EXTRAS=${MINERU_EXTRAS}" \
    -f mineru-image/runtime/Dockerfile .
fi

echo "Done."
echo "  source:  ${SOURCE_TAG}"
echo "  runtime: ${RUNTIME_TAG}"
