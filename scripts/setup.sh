#!/usr/bin/env bash
# One-shot local setup: create a venv, install dev dependencies, seed .env.
set -euo pipefail
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements-dev.txt
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill in real values before running."
fi
echo "Setup complete. Activate the venv with:  source .venv/bin/activate"
