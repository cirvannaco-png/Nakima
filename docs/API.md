# Nakima API Reference

FastAPI auto-generates interactive documentation. With the server running:

| URL | Description |
|---|---|
| `http://localhost:8000/docs` | Swagger UI (try requests in-browser) |
| `http://localhost:8000/redoc` | ReDoc reference |
| `http://localhost:8000/openapi.json` | Raw OpenAPI 3 schema |

---

## Authentication

All API endpoints are currently unauthenticated (Nakima trusts your network boundary). Webhook endpoints are HMAC-SHA256 verified using `GITHUB_WEBHOOK_SECRET`.

> Production deployments should add a reverse proxy with IP allow-listing or mTLS.

---

## Endpoints

### Health

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe — always 200 if server is up |
| GET | `/ready` | Readiness probe — 200 when DB is reachable |

---

### Repositories

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/repositories/index` | Index (clone + analyse) a repository |
| GET | `/api/v1/repositories/{repo}/health` | Repository health score and metrics |
| GET | `/api/v1/repositories/{repo}/analysis` | Full AST analysis results |
| GET | `/api/v1/repositories/` | List all indexed repositories |

**POST `/api/v1/repositories/index`**
```json
{
  "repo_full_name": "owner/repo",
  "github_token": "ghp_..."
}
```

---

### Tasks (Issue → PR automation)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/tasks/` | Create a new automation task |
| GET | `/api/v1/tasks/{task_id}` | Get task status and result |
| DELETE | `/api/v1/tasks/{task_id}` | Cancel a running task |
| GET | `/api/v1/tasks/` | List all tasks |

**POST `/api/v1/tasks/`**
```json
{
  "repo_full_name": "owner/repo",
  "issue_number": 42,
  "github_token": "ghp_..."
}
```

**Task status values:** `pending`, `running`, `success`, `failed`, `cancelled`

---

### Security (NSIL)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/security/{repo}/scan` | Run full NSIL scan |
| GET | `/api/v1/security/{repo}/findings` | List open security findings |

**POST `/api/v1/security/{repo}/scan`**
```json
{
  "github_token": "ghp_...",
  "target_url": "https://your-deployment.example.com",
  "run_pentest_simulator": false
}
```

> `target_url` triggers DAST. `run_pentest_simulator: true` additionally runs active pentest checks (requires GitHub ownership verification).

**Response:**
```json
{
  "score": 82.5,
  "counts_by_severity": {"critical": 0, "high": 1, "medium": 3, "low": 2},
  "total_open": 6,
  "new_finding_count": 2,
  "resolved_finding_count": 1,
  "scanners_run": ["secrets", "config", "sast", "deps", "dast"],
  "scanners_skipped": ["virus"]
}
```

---

### Intelligence (Decision Registry + Event Log)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/intelligence/{repo}/decisions` | Record an engineering decision |
| GET | `/api/v1/intelligence/{repo}/decisions` | List decisions |
| GET | `/api/v1/intelligence/{repo}/events` | List task events |
| POST | `/api/v1/intelligence/{repo}/report` | Generate PDF engineering report |
| GET | `/api/v1/intelligence/{repo}/report/latest` | Download latest PDF report |

---

### NEIS

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/neis/{repo}/evolve` | Run a NEIS evolution cycle |
| GET | `/api/v1/neis/{repo}/status` | Current NEIS state |
| POST | `/api/v1/neis/{repo}/analyze` | Analyze a specific issue |

---

### Documents

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/documents/{repo}/upload` | Upload a PDF or DOCX context document |
| GET | `/api/v1/documents/{repo}/` | List uploaded documents |
| DELETE | `/api/v1/documents/{repo}/{doc_id}` | Delete a document |

Upload uses `multipart/form-data`. Accepted types: `application/pdf`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document`.

---

### GitHub Webhook

| Method | Path | Description |
|---|---|---|
| POST | `/github/webhook` | Receives GitHub App events |

Requires `X-Hub-Signature-256` header for HMAC verification.

---

## Error Responses

All errors follow RFC 7807 (Problem Details):
```json
{
  "detail": "Repository not indexed yet — POST /repositories/index first"
}
```

| Status | Meaning |
|---|---|
| 400 | Bad request (validation failure, missing required field) |
| 403 | Forbidden (target ownership check failed) |
| 404 | Resource not found |
| 422 | Request body schema validation failed |
| 502 | Upstream service error (GitHub API, target URL unreachable) |
