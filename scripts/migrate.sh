#!/usr/bin/env bash
# Apply Alembic migrations against the configured database.
set -euo pipefail
exec alembic upgrade head
