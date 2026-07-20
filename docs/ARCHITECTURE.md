# Nakima Architecture Guide

## Overview

Nakima is a FastAPI application deployed as a GitHub App. It reacts to GitHub webhook events (primarily `issues.opened` and `issues.labeled`) and drives a multi-stage autonomous pipeline that produces a validated Pull Request.

---

## System Components

### 1. GitHub App Layer (`githubapp/`)

- **`auth.py`** — HMAC-SHA256 webhook signature verification; private-key JWT generation for GitHub App authentication; installation access token exchange.
- **`webhook.py`** — Receives and validates `POST /github/webhook` events; dispatches to the orchestrator.

### 2. API Gateway (`api/`)

- **`router.py`** — FastAPI app with CORS, rate limiting (SlowAPI), static file serving, and OpenTelemetry middleware.
- **`v1/`** — Versioned route modules:
  - `repositories` — Index, analyse, health-score
  - `tasks` — Create, inspect, cancel orchestration jobs
  - `security` — On-demand NSIL scans and findings history
  - `intelligence` — Decision registry and event log
  - `neis` — NEIS reasoning API
  - `documents` — Project document upload/retrieval
  - `health` — Liveness and readiness probes

### 3. AI Orchestrator (`orchestrator/`)

- **`workflow.py`** — The five-stage pipeline:
  1. **Intent Gate** — NEIS reasoning classifies and validates the issue intent
  2. **Plan** — `planner/planner.py` decomposes issue into implementable steps
  3. **Implement** — `agents/implementation.py` generates code changes
  4. **Security Gate** — NSIL scans generated diff before it touches a branch
  5. **Quality Gate** — Test coverage check; opens PR only when all gates pass

### 4. AI Agents (`agents/`)

| Agent | Responsibility |
|---|---|
| `analysis.py` | Repository structure summarisation, AST queries |
| `implementation.py` | Code generation from a structured plan |
| `code_review.py` | Automated review of generated diffs |
| `test_generation.py` | Unit test scaffolding for generated code |
| `security_agent.py` | SAST (bandit) and dependency audit (safety) via sandbox |
| `documentation.py` | Docstring and README generation |

### 5. NEIS — Nakima Engineering Intelligence System (`neis/`)

Four-engine reasoning pipeline:

```
Issue context
     │
     ▼
CognitiveEngine      — models what a developer would think first
     │
     ▼
EvidenceEngine       — gathers supporting data (codebase, history, docs)
     │
     ▼
DecisionEngine       — synthesises a ranked set of candidate solutions
     │
     ▼
ArbitrationEngine    — applies constraints (scope, risk, quality gates) and selects
     │
     ▼
Structured Decision
```

- **`analyzers/`** — Tech stack detection, dependency version intelligence (PyPI/npm live queries), project health signals
- **`reasoning/`** — The four engines above

### 6. Security Intelligence Layer — NSIL (`security/`)

All security checks are orchestrated by `security/nsil.py`:

| Scanner | Tool | Network |
|---|---|---|
| Secret Detection | `secret_scanner.py` (regex) | No |
| Config Security | `config_scanner.py` | No |
| SAST | bandit via sandbox | No |
| Dependency Audit | safety via sandbox | Yes (PyPI) |
| DAST | `dast.py` (httpx) | Yes (target) |
| Pentest Simulation | `pentest_simulator.py` | Yes (target, gated) |
| Virus Scan | ClamAV / `virus_scanner.py` | No |

**SSRF Guard** (`security/ssrf_guard.py`) — Rejects RFC-1918, loopback, link-local, and cloud-metadata-endpoint URLs before any outbound request.

**Target Binding** (`security/target_binding.py`) — Before DAST or pentest runs, verifies that `target_url` is associated with the repository (homepage, GitHub Pages, deployment records) — prevents scanning unrelated targets.

### 7. Repository Engine (`repository/`)

- **`engine.py`** — Authenticated Git clone via `gitpython`
- **`analysis.py`** — Tree-sitter AST parsing for Python, TypeScript, Go
- **`graph_builder.py`** — NetworkX dependency graph construction
- **`health.py`** — Radon complexity scoring; health-score aggregation

### 8. Execution Sandbox (`execution/`)

- **`sandbox.py`** — `docker run --network none` — isolated execution for code validation
- **`tool_registry.py`** — Per-language tool matrix (pytest, flake8, jest, golangci-lint, …)

### 9. Memory Layer (`memory/`)

- **`knowledge_graph.py`** — Persistent cross-task learning; feeds NEIS evidence gathering
- **`learning.py`** — Outcome feedback loop; improves plan quality over time

### 10. Intelligence Layer (`intelligence/`)

- **`decision_registry.py`** — Append-only log of every architectural decision Nakima makes
- **`event_log.py`** — Structured event log per task (files changed, tests run, risk level)

---

## Data Flow — Issue to PR

```
1. GitHub sends webhook → POST /github/webhook
2. Signature verified (HMAC-SHA256)
3. Task record created in PostgreSQL
4. Orchestrator.run_task() dispatched (async background)
5. Repository cloned to /tmp/<task-id>/
6. NEIS Intent Gate runs
7. Planner produces step list
8. ImplementationAgent generates code
9. NSIL Security Gate scans diff
10. ValidationPipeline runs (format, lint, build, test, security)
11. QualityGate evaluates test coverage
12. DecisionRegistry + EventLog records outcome
13. Git branch created, PR opened via GitHub API
14. Cleanup: /tmp/<task-id>/ removed
```

---

## Database Schema

PostgreSQL via SQLAlchemy async + Alembic migrations.

| Table | Purpose |
|---|---|
| `repositories` | Indexed repositories |
| `tasks` | Orchestration job lifecycle |
| `security_findings` | NSIL findings with regression tracking |
| `engineering_decisions` | Decision registry entries |
| `engineering_events` | Event log entries |
| `engineering_reports` | Generated PDF report metadata |
| `project_documents` | Uploaded document metadata |

---

## Plugin Architecture

New AI providers implement `providers/base.py:BaseProvider` and register via `core/config.py:Settings.DEFAULT_AI_PROVIDER`.

New security scanners implement a `scan(repo_dir) → list[Finding]` interface and are added to `security/nsil.py:SecurityIntelligenceLayer.scan()`.

New agents implement `agents/base.py:BaseAgent` and handle `AgentRequest` actions.
