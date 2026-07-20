# Nakima Deployment Guide

## Docker (Recommended)

The `docker-compose.yml` in the repository root covers local and single-node production deployments.

### Production checklist before going live

- [ ] `ENVIRONMENT=production` in `.env`
- [ ] `GITHUB_WEBHOOK_SECRET` is a cryptographically random 32+ byte string
- [ ] Private key path is mounted as a volume secret (not baked into the image)
- [ ] PostgreSQL and Redis are not exposed on public interfaces (remove port bindings in `docker-compose.yml`)
- [ ] TLS termination via a reverse proxy (nginx/Caddy/Traefik) in front of port 8000
- [ ] ClamAV `freshclam` is running and signatures are current
- [ ] `/health` and `/ready` endpoints registered with your load balancer
- [ ] Alembic migrations run before first boot: `alembic upgrade head`
- [ ] `REPORTS_DIR` points to a persistent volume
- [ ] Docker socket mount (`/var/run/docker.sock`) is intentional (required for sandbox)

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GITHUB_APP_ID` | ✓ | — | GitHub App numeric ID |
| `GITHUB_PRIVATE_KEY` | ✓* | — | Raw PEM contents (newlines as `\n`) |
| `GITHUB_PRIVATE_KEY_PATH` | ✓* | — | Path to `.pem` file (*either* this or above) |
| `GITHUB_WEBHOOK_SECRET` | ✓ | — | HMAC-SHA256 webhook signature secret |
| `GITHUB_TOKEN` | ✓ | — | PAT for GitHub Models inference |
| `DEFAULT_AI_PROVIDER` | | `github` | `github`, `anthropic`, `openai`, `deepseek` |
| `GITHUB_MODELS_MODEL` | | `openai/gpt-4o-mini` | Model to use with GitHub Models |
| `ANTHROPIC_API_KEY` | | — | Required if provider=anthropic |
| `OPENAI_API_KEY` | | — | Required if provider=openai |
| `DATABASE_URL` | | auto | Full asyncpg DSN; overrides DB_* parts |
| `DB_HOST` | | `localhost` | |
| `DB_PORT` | | `5432` | |
| `DB_USER` | | `nakima` | |
| `DB_PASSWORD` | | `nakima` | |
| `DB_NAME` | | `nakima` | |
| `REDIS_URL` | | auto | Full Redis DSN; overrides REDIS_* parts |
| `CLAMD_HOST` | | — | ClamAV daemon hostname; omit to disable virus scanning |
| `CLAMD_PORT` | | `3310` | |
| `SCAN_ON_PR` | | `true` | Run NSIL on every generated PR diff |
| `SANDBOX_IMAGE` | | `nakima-sandbox:latest` | Docker image for execution sandbox |
| `REPORTS_DIR` | | `./reports_output` | Directory for generated PDF reports |
| `LOG_FORMAT` | | `json` | `json` (structured) or `text` (dev) |
| `ENVIRONMENT` | | `development` | `development` or `production` |

---

## Google Cloud (GCE)

```bash
# 1. Build and push image
gcloud builds submit --tag gcr.io/YOUR_PROJECT/nakima:latest

# 2. Create Cloud SQL (PostgreSQL 16) instance
gcloud sql instances create nakima-db --database-version=POSTGRES_16 --tier=db-g1-small

# 3. Deploy
gcloud run deploy nakima \
  --image gcr.io/YOUR_PROJECT/nakima:latest \
  --platform managed \
  --region us-central1 \
  --set-env-vars ENVIRONMENT=production \
  --set-secrets GITHUB_PRIVATE_KEY=nakima-pem:latest \
  --set-secrets GITHUB_WEBHOOK_SECRET=nakima-webhook-secret:latest \
  --set-secrets GITHUB_TOKEN=nakima-github-token:latest
```

> Note: Cloud Run does not support Docker socket. For sandbox execution on GCP, replace `SandboxExecutor` with Cloud Run Jobs or use a GCE VM instead.

---

## AWS (ECS Fargate)

```bash
# Push to ECR
aws ecr create-repository --repository-name nakima
docker tag nakima:latest $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/nakima:latest
docker push $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/nakima:latest

# ECS task definition — use AWS Secrets Manager for all secrets
# RDS PostgreSQL 16 for managed database
# ElastiCache Redis for managed cache
```

---

## Health Probes

| Endpoint | Type | Check |
|---|---|---|
| `GET /health` | Liveness | Returns `{"status": "ok"}` |
| `GET /ready` | Readiness | Checks DB connectivity |

Configure Kubernetes/ECS/Cloud Run to use `/ready` for readiness and `/health` for liveness.

---

## Scaling

- **Stateless:** The `app` container is stateless (all state in PostgreSQL + Redis). Scale horizontally.
- **Workers:** Increase Uvicorn `--workers` for CPU-bound workloads.
- **Sandbox:** Each sandbox execution spawns a Docker container. Scale with more Docker hosts or switch to Kubernetes Jobs.
- **Database pool:** Adjust `DB_POOL_SIZE` (default: 20) for high concurrency.
