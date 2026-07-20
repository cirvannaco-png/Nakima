# Nakima API

FastAPI auto-generates interactive documentation. With the server running
(`./scripts/dev.sh` or `docker compose up`):

| URL | Description |
| --- | --- |
| `http://localhost:8000/docs` | Swagger UI (try requests in-browser) |
| `http://localhost:8000/redoc` | ReDoc reference |
| `http://localhost:8000/openapi.json` | Raw OpenAPI 3 schema |

A checked-in copy of the schema lives at [`docs/openapi.json`](./openapi.json).
Regenerate it with:

```bash
./scripts/export-openapi.sh
```

## Routes at a glance

| Prefix | Purpose |
| --- | --- |
| `/api/v1/tasks` | Create / inspect / cancel orchestration tasks |
| `/api/v1/repositories` | Register repos, run analysis, fetch health scores |
| `/api/v1/memory` | Knowledge-graph queries and learning feedback |
| `/api/v1/agents` | List available agents and capabilities |
| `/github/webhook` | GitHub App webhook receiver (HMAC-verified) |
| `/health`, `/ready` | Liveness / readiness probes |
