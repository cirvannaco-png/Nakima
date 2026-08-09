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
| **Evolution review gate** | Roadmap recommendations stay proposals until a human accepts or dismisses them; accepting can open the GitHub issue |
| **Market research (optional)** | Research → Judge → Opportunity pipeline turns external signals into proposals; disabled until a search backend is configured, and nothing it produces reaches the roadmap without an explicit promotion call |
| **Sandbox lab & self-healing** | Ephemeral, network-isolated container reproduces a failure, generates bounded multi-model candidate fixes, validates each against the full suite, and routes the result to human review |
| **Token budget compression** | Trims planner context to a token budget, keeping high fan-in files so large repos stay within provider limits |
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

## Self-Evolution Review Gate

NEIS analyses a repository and produces an **evolution roadmap** — a ranked list
of recommendations. Nothing in that roadmap acts on its own: every item starts as
`proposed` and needs an explicit human decision before it becomes work.

```bash
# Read the roadmap
curl http://localhost:8000/api/v1/neis/{owner}%2F{repo}/roadmap

# Accept an item and open a GitHub issue for it
curl -X PATCH http://localhost:8000/api/v1/neis/{owner}%2F{repo}/roadmap/items/{item_id} \
  -H "Content-Type: application/json" \
  -d '{"status": "accepted", "github_token": "<PAT with repo scope>"}'

# Dismiss an item (never touches GitHub)
curl -X PATCH http://localhost:8000/api/v1/neis/{owner}%2F{repo}/roadmap/items/{item_id} \
  -H "Content-Type: application/json" \
  -d '{"status": "dismissed"}'
```

Notes:

- `status` accepts only `accepted` or `dismissed`. Anything else is rejected with `422`.
- `github_token` is optional. Omit it to record the decision without opening an issue.
- Issue creation is **idempotent** on the item's stored `issue_number`, so retries and
  double-clicks never open duplicate issues.
- If GitHub is unreachable, the review decision is still saved; the item keeps
  `issue_url: null` until a later accept call succeeds.
- The issue Nakima opens is an ordinary issue, so the existing
  `POST /github/webhook` → orchestrator path picks it up like any human-filed one.

The `issue_number` / `issue_url` columns arrive in migration
`0010_neis_roadmap_item_issue_tracking`, so run `alembic upgrade head` after pulling.

---

## Market Research Pipeline

A separate, optional pipeline for external signal — competitor moves, framework
changes, UX trends — that the roadmap above has no way to see, since NEIS's
recommendations are deliberately limited to facts it can measure about the
repository itself (see `neis/analyzers/innovation_engine.py`). Three stages:

- **Research Agent** (`market_research/research_scout.py`) — runs your queries
  against a configurable search backend and stores each hit as an
  `ExternalSignal`. No backend is chosen out of the box; set
  `MARKET_RESEARCH_SEARCH_API_KEY` (see `.env.example`) once you've picked one.
  Until then, scans run and report zero signals rather than failing.
- **Judge Agent** (`market_research/judge.py`) — screens every pending signal
  for relevance and credibility before anything downstream sees it.
  **Fail-closed**: no AI provider configured, or a response that doesn't parse,
  is rejected, never silently accepted.
- **Opportunity Engine** (`market_research/opportunity_engine.py`) — turns
  only the accepted signals into `ExternalOpportunity` proposals, each with
  the provider's own (self-reported, unverified) confidence score.

Opportunities never reach the roadmap or the Coding Agent on their own. A
human has to explicitly promote one — at that point it becomes an ordinary
`EvolutionRoadmapItem` (category `market_opportunity`) and goes through the
same accept/dismiss gate as everything else above.

```bash
# Run a scan
curl -X POST http://localhost:8000/api/v1/market-research/{owner}%2F{repo}/scan \
  -H "Content-Type: application/json" \
  -d '{"queries": ["abandoned cart recovery competitors"], "repo_context": "..."}'

# Review what it found
curl http://localhost:8000/api/v1/market-research/{owner}%2F{repo}/opportunities

# Promote one into the roadmap, or dismiss it
curl -X POST http://localhost:8000/api/v1/market-research/{owner}%2F{repo}/opportunities/{id}/promote
curl -X POST http://localhost:8000/api/v1/market-research/{owner}%2F{repo}/opportunities/{id}/dismiss
```

Migration `0011_market_research` adds the `external_signals` and
`external_opportunities` tables and the `market_opportunity` roadmap category.

---

## Planner Token Compression

`planner/token_compressor.py` sits between `ContextBuilder` and the AI provider and
keeps a context payload inside a token budget:

- the requirement text is never dropped;
- code snippets are kept in descending **fan-in** order (files that more of the
  repository depends on survive first);
- the dependency subgraph is trimmed to the files that actually survived, so the
  provider never sees edges pointing at content that isn't in the prompt;
- the returned payload carries a `compression` report (`snippets_kept`,
  `snippets_dropped`, `estimated_tokens_used`) for debugging truncated prompts.

```python
from planner.token_compressor import TokenCompressor

payload = TokenCompressor(max_tokens=8000).compress(context)
```

It is a pure function over an already-built context dict and is not yet wired into
`ContextBuilder`'s call site.

---

## Security Gate Benchmark

The Security Gate is verified by a ground-truth benchmark rather than a quality
score: `tests/benchmark_security_gates.py` runs the real scanners
(`SecretScanner`, `ConfigSecurityScanner`, `VirusScanner` with an EICAR-aware
mocked clamd) through the real decision layer (`RiskScorer`,
`security_gate_should_block`) against scratch repositories on disk.

Each case has a known right answer, so the required pass rate is 100% — a
failure is either a threat that stopped blocking or clean input that started
blocking.

```bash
pytest tests/benchmark_security_gates.py -v -s
```

See [BENCHMARK_SECURITY_GATES.md](BENCHMARK_SECURITY_GATES.md) for the case
corpus, how to add cases, and how to verify the CI-level scanners by hand.

---

## Sandbox Lab & Self-Healing

Where a proposed fix is proven before a human ever sees it. Every run happens in
an **ephemeral container with `network: none`**, against a read-only clone pinned
to a single commit — never against the live repository.

- **Orchestrator** (`orchestrator/main.py`) — accepts a run request, checks the
  repository's lab opt-in, launches the sandbox container, collects exactly one
  `result.json`, and destroys the container **always** (including on failure and
  timeout). Concurrency and container TTL are hard-capped.
- **Sandbox entrypoint** (`sandbox_image/entrypoint.py`) — clones at the commit,
  records a baseline full-suite run as the control, optionally runs a CVE scan or
  synthetic injection, then hands off to the healing loop and writes its result.
- **Self-healing loop** (`orchestrator/self_healing.py`) — diagnose, generate
  candidate fixes across multiple providers, validate **each candidate against
  the entire test suite**, and compute (never assert) a confidence score.
  Bounded by `MAX_HEAL_ATTEMPTS`: on exhaustion it escalates to human review with
  the full diagnostic trail rather than looping. Failures classified as security
  findings always route to human review regardless of confidence.

Sandbox results are tenant-isolated rows (`db/schema.sql`) and are surfaced for
review — nothing is applied to a repository automatically.

Learning from those runs is deliberately offline: an outcome becomes a
`pattern_memory` candidate with `promoted_to_base_model = false` and only a
separate, manual batch review flips it. See
[NEIS Learning Policy](docs/NEIS_LEARNING_POLICY.md).

The lab is **v0.1 and partly stubbed** — clone-URL minting, container log
polling, and the model wiring in `diagnose_failure` / `generate_candidate_fix`
are not production paths yet. Every gap is listed in
[Known Gaps](docs/known-gaps.md); read it before running the lab against a real
repository.

See [Lab & Sandbox Overview](docs/LAB_OVERVIEW.md) for the full data flow.

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
| [Security Gate Benchmark](BENCHMARK_SECURITY_GATES.md) | Ground-truth block/pass corpus for the security gate |
| [Lab & Sandbox Overview](docs/LAB_OVERVIEW.md) | Sandbox isolation model, self-healing data flow, review path |
| [NEIS Learning Policy](docs/NEIS_LEARNING_POLICY.md) | Why sandbox outcomes never update the shared model live |
| [Known Gaps](docs/known-gaps.md) | What is real vs. stubbed in the lab / self-healing v0.1 |
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
