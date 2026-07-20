# Nakima Operations Guide

## Monitoring

### Metrics (Prometheus)

Nakima exposes Prometheus metrics at `GET /metrics`:

| Metric | Type | Description |
|---|---|---|
| `nakima_tasks_total` | Counter | Tasks created, by status |
| `nakima_task_duration_seconds` | Histogram | Task pipeline duration |
| `nakima_security_findings_total` | Counter | Findings by severity |
| `nakima_api_request_duration_seconds` | Histogram | HTTP request latency by endpoint |

Scrape config for Prometheus:
```yaml
scrape_configs:
  - job_name: nakima
    static_configs:
      - targets: ['nakima:8000']
    metrics_path: /metrics
```

### Tracing (OpenTelemetry)

Set `OTEL_EXPORTER_OTLP_ENDPOINT` to send traces to Jaeger, Tempo, or any OTLP-compatible backend:

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
OTEL_SERVICE_NAME=nakima
```

### Logging

Nakima emits JSON-structured logs by default (`LOG_FORMAT=json`):

```json
{"timestamp": "2026-07-20T12:00:00Z", "level": "INFO", "message": "Task completed", "task_id": "...", "pr_url": "..."}
```

Set `LOG_FORMAT=text` for human-readable development logs.

Key log fields: `task_id`, `repo_full_name`, `issue_number`, `pr_url`, `error`, `duration_s`.

---

## Health Checks

```bash
# Liveness (server up)
curl http://localhost:8000/health

# Readiness (DB reachable)
curl http://localhost:8000/ready
```

Both return `{"status": "ok"}` on success.

---

## Backups

### PostgreSQL

```bash
# Dump
docker compose exec db pg_dump -U nakima nakima > backup_$(date +%Y%m%d).sql

# Restore
docker compose exec -T db psql -U nakima nakima < backup_20260720.sql
```

Schedule daily backups. Keep at least 7 days of backups.

### Reports

`REPORTS_DIR` (default: `./reports_output`) contains generated PDF reports. Include in your backup rotation.

---

## Incident Response

### Task stuck in `running`

```bash
# Check recent logs
docker compose logs --tail=200 app | grep <task_id>

# Force-fail the task via DB
docker compose exec db psql -U nakima nakima \
  -c "UPDATE tasks SET status='failed', error='Manually cancelled by operator' WHERE id='<task_id>'"
```

### Database connection errors

```bash
docker compose restart db
# Wait for health check to pass
docker compose logs db --tail=20
```

### Sandbox containers leaking

```bash
# List orphaned sandbox containers
docker ps -a --filter "ancestor=nakima-sandbox:latest"

# Remove them
docker container prune --filter "label=nakima.sandbox=true"
```

### ClamAV signatures stale

```bash
docker compose exec clamav freshclam
docker compose restart clamav
```

---

## Maintenance

### Upgrade dependencies

1. Update version pins in `requirements.txt`
2. Run `pip install -r requirements.txt` locally
3. Run `pytest` — all tests must pass
4. Open a PR; CI runs `safety check` and Trivy

### Database migrations

```bash
# After adding a new SQLAlchemy model/column:
alembic revision --autogenerate -m "describe the change"
# Review the generated file in alembic/versions/
alembic upgrade head
```

Always review auto-generated migrations before running them in production.

### Rotating secrets

1. Generate new `GITHUB_WEBHOOK_SECRET` in GitHub App settings
2. Update `.env` / secret manager
3. Restart the `app` container
4. No database changes required (webhook secret is not persisted)

For the GitHub private key: generate a new key in GitHub App settings, add it, update `GITHUB_PRIVATE_KEY_PATH`, restart, then delete the old key from GitHub.

---

## Scaling

### Horizontal scaling

`app` is stateless. Run multiple instances behind a load balancer. All share the same PostgreSQL and Redis.

### Database connection pooling

For >10 app instances, add PgBouncer in front of PostgreSQL and set `DB_POOL_SIZE=5` per instance.

### Background task queue

For high-volume deployments (>100 tasks/hour), replace the in-process asyncio background tasks with Celery + Redis as the broker, using the same `workflow.py` logic.
