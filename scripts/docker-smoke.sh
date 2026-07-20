#!/usr/bin/env bash
# Docker smoke test: build the images, boot the stack, and hit the health
# endpoints. Fails loudly if anything is missing.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[smoke] building images"
docker compose build --pull

echo "[smoke] starting stack"
docker compose up -d db redis
docker compose up -d app

cleanup() {
  echo "[smoke] tearing down"
  docker compose logs --no-color --tail=100 app || true
  docker compose down -v --remove-orphans
}
trap cleanup EXIT

echo "[smoke] waiting for /health"
for i in $(seq 1 40); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "[smoke] health OK after ${i}s"
    break
  fi
  sleep 1
  if [ "$i" = "40" ]; then
    echo "[smoke] app never became healthy" >&2
    exit 1
  fi
done

echo "[smoke] /ready"
curl -fsS http://localhost:8000/ready | tee /dev/stderr

echo "[smoke] /openapi.json"
curl -fsS http://localhost:8000/openapi.json | head -c 400
echo

echo "[smoke] PASS"
