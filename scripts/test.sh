#!/usr/bin/env bash
# Run the full test suite the same way CI does.
set -euo pipefail
export GITHUB_APP_ID="${GITHUB_APP_ID:-123456}"
export GITHUB_WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET:-ci-test-secret}"
export ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-sk-ci-placeholder}"
exec pytest -v "$@"
