#!/usr/bin/env bash
# Build Mathpix worker image. Uses Docker daemon builder to avoid Buildx
# docker-container driver "failed to build: EOF" on some setups.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer default builder (usually docker driver); else legacy build
if docker buildx inspect default &>/dev/null 2>&1; then
  docker buildx build --builder default -f Dockerfile.mathpix-worker -t readmybook-mathpix-worker:latest .
else
  DOCKER_BUILDKIT=0 docker build -f Dockerfile.mathpix-worker -t readmybook-mathpix-worker:latest .
fi
echo "Image built: readmybook-mathpix-worker:latest"
