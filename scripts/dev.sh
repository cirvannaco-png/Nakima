#!/usr/bin/env bash
# Run the FastAPI app locally with autoreload.
set -euo pipefail
if [ ! -f .env ]; then
  echo "No .env found — copying .env.example. Fill in the real values before running." >&2
  cp .env.example .env
fi
exec uvicorn api.router:app --host 0.0.0.0 --port 8000 --reload
