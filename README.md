# Nakima — Engineering Intelligence Platform

> **Autonomous AI GitHub App** — analyzes repositories, plans changes, generates code, validates quality, and opens pull requests from issues. Production-grade, security-first.

[![CI](https://github.com/cirvannaco-png/Nakima/actions/workflows/ci.yml/badge.svg)](https://github.com/cirvannaco-png/Nakima/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)

---

## What Is Nakima?

Nakima is a self-hosted GitHub App that turns GitHub Issues into validated Pull Requests — automatically. It combines:

- **Repository Intelligence** — AST-based code analysis, dependency graphs, health scoring
- **AI Orchestration** — multi-provider LLM planning, code generation, and review
- **Security Intelligence Layer (NSIL)** — secret detection, SAST, DAST, dependency audits, and optional penetration-test simulation
- **Nakima Engineering Intelligence System (NEIS)** — reasoning engine with cognitive, evidence, decision, and arbitration sub-engines
- **Quality Gate** — test coverage enforcement before any PR is opened
- **Engineering Intelligence Reports** — PDF reports covering decisions, events, and findings

> **Using Nakima:** Install the GitHub App (once publicly launched) from [github.com/apps/nakima](https://github.com/apps/nakima). You do not need to self-host. See the [User Guide](docs/USER_GUIDE.md).
>
> **Source code:** Available for audit only. See [LICENSE](LICENSE) for permitted use.

---

## Architecture Overview

```
GitHub Issue
     │
     ▼
┌─────────────────────────────────────────────────────┐
│                  GitHub App (Webhook)                │
│           githubapp/  ←  HMAC verified               │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│              AI Orchestrator                        │
│   orchestrator/workflow.py                          │
│   ┌──────────────────────────────────────────────┐  │
│   │   Planner → Implementer → Validator → PR     │  │
│   └──────────────────────────────────────────────┘  │
└───┬──────────┬──────────────┬───────────────────────┘
    │          │              │
    ▼          ▼              ▼
 Agents    Repository     Security
 agents/   repository/    security/nsil.py
           analysis.py    (NSIL — all 4 gates)
    │          │              │
    ▼          ▼              ▼
 Providers  Memory/Graph   NEIS Reasoning
 providers/ memory/        neis/reasoning/
 (GitHub    knowledge      cognitive, evidence,
  Models,   graph          decision, arbitration
  Claude,                  engines
  OpenAI)
    │
    ▼
 Execution Sandbox
 execution/ (Docker-isolated)
```

---

## Core Features

| Feature | Description |
|---|---|
| **Issue → PR automation** | Reads an issue, plans implementation steps, generates code, validates, opens PR |
| **NEIS Reasoning** | Four-engine reasoning: cognitive modelling → evidence gathering → decision synthesis → arbitration |
| **NSIL Security** | Secret scan + config scan + SAST (bandit) + dependency audit (safety) + DAST + pentest simulation |
| **Repository health** | AST analysis, complexity scoring, dependency graph, tech stack detection |
| **AI provider agnostic** | GitHub Models (free default), Anthropic Claude, OpenAI GPT-4, DeepSeek |
| **Engineering reports** | PDF reports with decision registry, event log, and security findings |
| **Document upload** | Ingest PDF/DOCX context documents for repository-aware Q&A |
| **Quality Gate** | Blocks PRs when source changes have no accompanying test changes |
| **Virus scanning** | ClamAV integration for uploaded documents |
| **Command Centre** | Real-time dashboard at `/` |

---

## Quick Start (Self-Hosted)

> Prerequisites: Docker ≥ 24, Docker Compose ≥ 2.20, a GitHub App with `issues: read`, `contents: write`, `pull_requests: write` permissions.

```bash
# 1 — Clone
git clone https://github.com/cirvannaco-png/Nakima.git
cd Nakima

# 2 — Configure
cp .env.example .env
# Fill in GITHUB_APP_ID, GITHUB_PRIVATE_KEY_PATH, GITHUB_WEBHOOK_SECRET, GITHUB_TOKEN

# 3 — Build & start
docker compose up --build -d

# 4 — Run migrations
docker compose exec app alembic upgrade head

# 5 — Verify
curl http://localhost:8000/health
```

The Command Centre dashboard is at `http://localhost:8000/`.
API docs (Swagger) are at `http://localhost:8000/docs`.

---

## Documentation

| Guide | Description |
|---|---|
| [Architecture Guide](docs/ARCHITECTURE.md) | System design, data flow, component responsibilities |
| [Installation Guide](docs/INSTALLATION.md) | Prerequisites, setup, configuration |
| [Deployment Guide](docs/DEPLOYMENT.md) | Docker, cloud (GCP/AWS), env vars, health checks |
| [API Reference](docs/API.md) | All REST endpoints with request/response schemas |
| [Developer Guide](docs/DEVELOPER_GUIDE.md) | Dev setup, coding standards, branching, contribution |
| [User Guide](docs/USER_GUIDE.md) | Using the GitHub App end-to-end |
| [Testing Guide](docs/TESTING.md) | Unit, integration, E2E, coverage requirements |
| [Security Guide](docs/SECURITY.md) | Secrets, auth, NSIL, dependency policy |
| [Operations Guide](docs/OPERATIONS.md) | Monitoring, logging, incident response, scaling |

---

## Roadmap

- [ ] Slack / Linear notification integration
- [ ] Multi-repository memory sharing
- [ ] Browser extension for one-click issue submission
- [ ] Fine-tuned model adapter for domain-specific codebases
- [ ] GitHub Enterprise Server support

---

## License

Nakima is **proprietary software**. Source code is available for audit only.
You may **not** copy, host, or redistribute it. See [LICENSE](LICENSE).

The hosted GitHub App (once launched) is available under separate Terms of Service.
