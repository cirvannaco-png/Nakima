#!/usr/bin/env bash
# One-shot bootstrap for the market research pipeline:
#   1. alembic upgrade head   (creates external_signals / external_opportunities)
#   2. POST /repositories/index   (the scan 404s on an unindexed repo)
#   3. POST /market-research/{repo}/scan   (Research -> Judge -> Opportunity Engine)
#
# Every write lands in Nakima's own database. Nothing here promotes an
# opportunity into the roadmap — promotion stays a deliberate, separate call
# (POST /market-research/opportunities/{id}/promote) and still requires the
# usual human accept step before it can reach GitHub or the orchestrator.
#
# Usage:
#   GITHUB_TOKEN=ghp_xxx scripts/market-research-bootstrap.sh \
#     cirvannaco/Cirvanna \
#     "Cirvanna, AI-powered fashion identity intelligence for the African luxury market" \
#     "AI fashion identity platform competitors" "luxury resale authentication startups"
#
# Env:
#   NAKIMA_API_URL  base URL of a running Nakima API (default http://localhost:8000)
#   GITHUB_TOKEN    required; used only for the clone during indexing
#   SKIP_MIGRATE=1  skip step 1
#   SKIP_INDEX=1    skip step 2 (repo already indexed)
set -euo pipefail

API="${NAKIMA_API_URL:-http://localhost:8000}"
REPO="${1:-}"
CONTEXT="${2:-}"
shift 2 2>/dev/null || true
QUERIES=("$@")

if [[ -z "$REPO" || -z "$CONTEXT" || ${#QUERIES[@]} -eq 0 ]]; then
  echo "usage: $0 <owner/repo> <repo_context> <query> [query ...]" >&2
  exit 2
fi
if [[ ${#QUERIES[@]} -gt 10 ]]; then
  echo "error: at most 10 queries (MarketResearchScanRequest.queries max_length=10)" >&2
  exit 2
fi
if [[ -z "${GITHUB_TOKEN:-}" && "${SKIP_INDEX:-}" != "1" ]]; then
  echo "error: GITHUB_TOKEN is required to index the repository (or set SKIP_INDEX=1)" >&2
  exit 2
fi

need() { command -v "$1" >/dev/null 2>&1 || { echo "error: $1 is required" >&2; exit 2; }; }
need curl
need python3

post() { # post <path> <json>
  curl -sS --fail-with-body -X POST "${API}$1" \
    -H "Content-Type: application/json" -d "$2"
}

if [[ "${SKIP_MIGRATE:-}" != "1" ]]; then
  echo "==> alembic upgrade head"
  alembic upgrade head
fi

if [[ "${SKIP_INDEX:-}" != "1" ]]; then
  echo "==> indexing ${REPO}"
  body=$(REPO="$REPO" python3 -c 'import json,os;print(json.dumps({"repo_full_name":os.environ["REPO"],"github_token":os.environ["GITHUB_TOKEN"]}))')
  post /api/v1/repositories/index "$body"
  echo
fi

echo "==> scanning ${REPO}"
scan_body=$(REPO_CONTEXT="$CONTEXT" python3 -c '
import json, os, sys
print(json.dumps({"queries": sys.argv[1:], "repo_context": os.environ["REPO_CONTEXT"]}))
' "${QUERIES[@]}")
post "/api/v1/market-research/${REPO}/scan" "$scan_body"
echo
echo "==> done. Review opportunities:"
echo "    curl ${API}/api/v1/market-research/${REPO}/opportunities"
