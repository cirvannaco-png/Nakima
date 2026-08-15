# Nakima Installation Guide

> This guide is for authorized contributors and auditors working with the source. It is not an invitation to self-host Nakima in production; see the hosted GitHub App for user access.

## Prerequisites

| Requirement | Minimum | Notes |
|---|---|---|
| Docker | 24.0+ | Required for sandbox execution |
| Docker Compose | 2.20+ | |
| GitHub Account | — | For GitHub App creation |
| PostgreSQL | 16+ | Managed by Docker Compose |
| Redis | 7+ | Managed by Docker Compose |

---

## 1 — Create the GitHub App

1. Go to **Settings → Developer settings → GitHub Apps → New GitHub App**
2. Set the following:
   - **App name:** `nakima-your-org` (must be globally unique)
   - **Homepage URL:** Your deployment URL
   - **Webhook URL:** `https://your-domain.com/github/webhook`
   - **Webhook secret:** Generate a strong random string (save it)
3. Permissions:
   - **Repository:** Issues (read), Contents (read & write), Pull requests (read & write), Metadata (read)
4. **Subscribe to events:** Issues
5. Click **Create GitHub App**
6. Note the **App ID**
7. Generate a **private key** and download the `.pem` file
8. Install the App on the repositories you want Nakima to manage

---

## 2 — Clone the Repository

```bash
git clone https://github.com/cirvannaco-png/Nakima.git
cd Nakima
```

---

## 3 — Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
# GitHub App
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY_PATH=./nakima-app.private-key.pem
GITHUB_WEBHOOK_SECRET=your-webhook-secret-here

# AI Provider (GitHub Models is free — just needs a PAT with "Models: read")
DEFAULT_AI_PROVIDER=github
GITHUB_TOKEN=ghp_your_github_pat

# These are set automatically by docker-compose — leave as-is for local
DATABASE_URL=postgresql+asyncpg://nakima:nakima@db:5432/nakima
REDIS_URL=redis://redis:6379/0
CLAMD_HOST=clamav
```

Place your downloaded `.pem` file at `./nakima-app.private-key.pem`.

---

## 4 — Build and Start

```bash
# Build all images (includes sandbox image)
docker compose build

# Start all services in the background
docker compose up -d

# Watch logs
docker compose logs -f app
```

Services started:
- `app` — Nakima API (port 8000)
- `db` — PostgreSQL 16 (port 5432)
- `redis` — Redis 7 (port 6379)
- `clamav` — ClamAV daemon (port 3310, ~1 min first-start for signature download)
- `sandbox` — Pre-built sandbox image (no running container; spawned on demand)

---

## 5 — Run Database Migrations

```bash
docker compose exec app alembic upgrade head
```

---

## 6 — Verify Installation

```bash
# Liveness
curl http://localhost:8000/health

# API docs
open http://localhost:8000/docs

# Command Centre dashboard
open http://localhost:8000/
```

---

## Updating

```bash
git pull
docker compose build app
docker compose up -d app
docker compose exec app alembic upgrade head
```

---

## Uninstalling

```bash
docker compose down -v  # -v removes named volumes (database data)
```
