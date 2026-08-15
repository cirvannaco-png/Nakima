# Nakima — Engineering Intelligence Platform

> **Autonomous AI GitHub App** — analyzes repositories, plans changes, generates code, validates quality, and opens pull requests from issues. Production-grade, security-first.

[![CI](https://github.com/cirvannaco-png/Nakima/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/cirvannaco-png/Nakima/actions/workflows/ci.yml)
[![Code Quality](https://github.com/cirvannaco-png/Nakima/actions/workflows/code-quality.yml/badge.svg?branch=main)](https://github.com/cirvannaco-png/Nakima/actions/workflows/code-quality.yml)
[![Deploy](https://github.com/cirvannaco-png/Nakima/actions/workflows/deploy.yml/badge.svg?branch=main)](https://github.com/cirvannaco-png/Nakima/actions/workflows/deploy.yml)
[![Staging](https://github.com/cirvannaco-png/Nakima/actions/workflows/staging.yml/badge.svg?branch=develop)](https://github.com/cirvannaco-png/Nakima/actions/workflows/staging.yml)
[![Container Scan](https://img.shields.io/badge/container%20scan-Trivy-1904DA.svg?logo=aquasecurity&logoColor=white)](https://github.com/cirvannaco-png/Nakima/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A580%25-brightgreen.svg)](https://github.com/cirvannaco-png/Nakima/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)

---

## What Is Nakima?

Nakima is a hosted GitHub App that turns GitHub Issues into validated Pull Requests — automatically. It combines:

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

## Access

Nakima is proprietary software. Source is available in this
repository for audit and security review only — it is not licensed
for self-hosting, deployment, or redistribution. See [LICENSE](./LICENSE).

To use Nakima on your repositories, install the hosted GitHub App:
[github.com/apps/nakima](https://github.com/apps/nakima) (once
publicly launched). Usage is governed by separate Terms of Service.
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

To go from a clean database to a first scan in one step, use
`scripts/market-research-bootstrap.sh` — it runs `alembic upgrade head`,
indexes the repository (the scan returns 404 on an unindexed repo), then
fires the scan. It stops there: promotion stays a separate, deliberate call.

```bash
GITHUB_TOKEN=ghp_xxx scripts/market-research-bootstrap.sh \
  cirvannaco/Cirvanna \
  "Cirvanna, AI-powered fashion identity intelligence for the African luxury market" \
  "AI fashion identity platform competitors"
```

Set `NAKIMA_API_URL` for a non-local API, and `SKIP_MIGRATE=1` / `SKIP_INDEX=1`
to skip steps you have already run.

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

## Deployment Pipelines

### Container Vulnerability Scanning

Trivy runs at three points in the pipeline, so no unscanned image can reach an environment:

| Stage | Scan | Gate |
| --- | --- | --- |
| CI (`trivy`) | `Dockerfile` and `Dockerfile.sandbox` images, OS + library CVEs | app image fails on fixable `CRITICAL`/`HIGH`; sandbox image is report-only |
| CI (`trivy-config`) | Dockerfile / IaC misconfigurations | Dockerfile fails on `CRITICAL`/`HIGH`; wider IaC is report-only |
| Deploy & Staging (`scan`) | the published GHCR image (`:latest` / `:staging`) | blocks the deploy on fixable `CRITICAL`/`HIGH` |

Every scan also uploads a SARIF report (including `MEDIUM` findings) to **Security → Code scanning**, categorised per image (`trivy-app`, `trivy-sandbox`, `trivy-production`, `trivy-staging`), and attaches it as a build artifact. `ignore-unfixed` is enabled so the gate only blocks on CVEs that actually have a patched version available.


Three GitHub Actions workflows form the delivery chain. Nothing deploys unless
CI is green on the exact commit being shipped.

```
push / PR ──► CI (lint, SAST, audit, tests+coverage, docker, trivy)
                │
        ┌───────┴────────┐
        │ branch=develop │ branch=main
        ▼                ▼
   Staging workflow   Deploy workflow
   ghcr :staging      ghcr :latest + :sha
   deploy hook        deploy hook
   /health gate       /health gate
        │                │
   fail ▼           fail ▼
   auto-rollback     auto-rollback
   (previous digest re-tagged + redeployed + re-verified)
```

| Workflow | Trigger | Purpose |
|---|---|---|
| [`ci.yml`](.github/workflows/ci.yml) | push to `main`/`develop`, every PR | Ruff + flake8, bandit, safety, pytest with an 80% coverage gate, Docker builds, Trivy scan |
| [`code-quality.yml`](.github/workflows/code-quality.yml) | push to `main`, every PR | Formatting and lint using the pins from `requirements-dev.txt` |
| [`staging.yml`](.github/workflows/staging.yml) | after CI succeeds on `develop`, or manual | Publishes `ghcr.io/<repo>:staging`, deploys staging, health-gates it, rolls back on failure |
| [`deploy.yml`](.github/workflows/deploy.yml) | after CI succeeds on `main`, or manual | Publishes `ghcr.io/<repo>:latest` + `:sha`, deploys production, health-gates it, rolls back on failure |

### Automated rollback

Before a new image is pushed, the pipeline records the digest currently behind
the `:latest` (production) or `:staging` tag. If the deploy hook fails or the
`/health` probe does not pass within five minutes, the `rollback` job:

1. Re-points the moving tag at the recorded known-good digest.
2. Re-fires the deploy hook so the platform pulls that image.
3. Re-verifies `/health` and fails loudly if the service is still unhealthy.

Rollback is skipped (with a notice, not a failure) when no previous image exists.

### Environments and configuration

Both deploy workflows use GitHub Environments so approvals and secrets are
scoped per stage. Missing configuration degrades to a skipped deploy rather
than a red build.

| Stage | Environment | Secret | Variable |
|---|---|---|---|
| Staging | `staging` | `RENDER_STAGING_DEPLOY_HOOK_URL` | `STAGING_URL` |
| Production | `production` | `RENDER_DEPLOY_HOOK_URL` | `PRODUCTION_URL` |

Branch flow: feature branch → PR → `develop` (staging) → `main` (production).

---

## Roadmap

- [ ] Slack / Linear notification integration
- [ ] Multi-repository memory sharing
- [ ] Browser extension for one-click issue submission
- [ ] Fine-tuned model adapter for domain-specific codebases
- [ ] GitHub Enterprise Server support

---

## Commit History

Every commit on `main`, newest first.

| Commit | Date | Summary |
|---|---|---|
| [`7b9cf0ed`](https://github.com/cirvannaco-png/Nakima/commit/7b9cf0ed541e9d041499b08ab9c4f0c52e09a101) | 2026-08-10 | test(deploy_agent): cover orchestrator, secrets store and adapter validation |
| [`c0316fc2`](https://github.com/cirvannaco-png/Nakima/commit/c0316fc2bba2c460bc51aedf265c190b1374943d) | 2026-08-10 | ci: fix failing lint/test pipelines and wire up deployment workflow |
| [`b69b4478`](https://github.com/cirvannaco-png/Nakima/commit/b69b44788f1dc1c9055677bc25fd099d1ceaa2fb) | 2026-08-10 | feat: integrate deploy agent adapters |
| [`3ba669f9`](https://github.com/cirvannaco-png/Nakima/commit/3ba669f971045fedb6e57fafc12d94b5aa7d1913) | 2026-08-09 | feat(scripts): one-shot market research bootstrap (migrate -> index -> scan) |
| [`d63891d9`](https://github.com/cirvannaco-png/Nakima/commit/d63891d9a8481d2da2adf166c0b15f7d823db613) | 2026-08-09 | fix: lint/format the lab commit, register market-research models, document the lab |
| [`73a5af07`](https://github.com/cirvannaco-png/Nakima/commit/73a5af07b29f53bf072cd57192161bf1eac614df) | 2026-08-09 | feat: add market research and sandbox lab materials |
| [`17d55a64`](https://github.com/cirvannaco-png/Nakima/commit/17d55a64e1e54177bea9d1709a6f365b0b77966a) | 2026-08-07 | test(security): ground-truth benchmark for the security gate |
| [`92dee0af`](https://github.com/cirvannaco-png/Nakima/commit/92dee0af97d13da4f1f5e64671eb9bb9e4f59e84) | 2026-08-06 | feat(neis): human review gate for roadmap items + planner token compressor |
| [`f4ede155`](https://github.com/cirvannaco-png/Nakima/commit/f4ede155a3801f9d793b5b0ca5086c4a19d06250) | 2026-08-06 | fix(ci): create Postgres enum types once in migrations, fix formatting, hermetic preflight test |
| [`2bec1f3e`](https://github.com/cirvannaco-png/Nakima/commit/2bec1f3ef002430ca5ed0a5b08d86c0f554e2712) | 2026-07-31 | fix: three deployment-blocking bugs — Docker eager-init crash, misleading provider preflight, planner eager get_provider |
| [`ca3e28a8`](https://github.com/cirvannaco-png/Nakima/commit/ca3e28a8738b0bfdfa153688ea3984c3534bae9a) | 2026-07-31 | fix: resolve Render deployment failures |
| [`84ef3498`](https://github.com/cirvannaco-png/Nakima/commit/84ef3498d9e1034a08d4f6f49f32cc1074204242) | 2026-07-31 | chore(deploy): pin Python 3.12 for Render via .python-version and render.yaml |
| [`78e59c08`](https://github.com/cirvannaco-png/Nakima/commit/78e59c0848fedf40b7acf3842d5bfc254896bad2) | 2026-07-31 | fix(preflight): skip false-positive production checks when PaaS provides DATABASE_URL or GitHub App is unconfigured |
| [`a759ef1e`](https://github.com/cirvannaco-png/Nakima/commit/a759ef1ee890741b9cae9ca66e913e2f93d520ce) | 2026-07-30 | fix(migrations): idempotent enum creation + drop stale signalstatus type |
| [`0775bbbb`](https://github.com/cirvannaco-png/Nakima/commit/0775bbbbd4c6813ea07371519f550ec7ce87c4bc) | 2026-07-25 | style: expand inline async methods for ruff format compliance |
| [`3fc2ab9d`](https://github.com/cirvannaco-png/Nakima/commit/3fc2ab9d848b5ce36984a6bc43b5ba64115f7179) | 2026-07-25 | fix(lint): UP042 replace (str, enum.Enum) with enum.StrEnum in quality/gate.py |
| [`f9d8dd08`](https://github.com/cirvannaco-png/Nakima/commit/f9d8dd0868c40c442349ef916459f3d083c7bf51) | 2026-07-25 | fix(lint): UP042 replace (str, enum.Enum) with enum.StrEnum in neis/reasoning/arbitration_engine.py |
| [`302d05e8`](https://github.com/cirvannaco-png/Nakima/commit/302d05e859749aed360f75b1a311718572d88854) | 2026-07-25 | fix(lint): UP042 replace (str, enum.Enum) with enum.StrEnum in models/task.py |
| [`e7430c32`](https://github.com/cirvannaco-png/Nakima/commit/e7430c321fda63f3d4279593681f99b29beb0eaf) | 2026-07-25 | fix(lint): UP042 replace (str, enum.Enum) with enum.StrEnum in models/neis/technology_intel.py |
| [`a2ff09cd`](https://github.com/cirvannaco-png/Nakima/commit/a2ff09cdc347903b700a40c35bd2c51d6e11ec31) | 2026-07-25 | fix(lint): UP042 replace (str, enum.Enum) with enum.StrEnum in models/neis/evolution_roadmap.py |
| [`f812a09c`](https://github.com/cirvannaco-png/Nakima/commit/f812a09c75aa24e160f5425aafa7d98e29b5ed31) | 2026-07-25 | fix(lint): UP042 replace (str, enum.Enum) with enum.StrEnum in models/graph.py |
| [`abcee479`](https://github.com/cirvannaco-png/Nakima/commit/abcee479b14cfa0a6f4129b1a8bb96ded48911c4) | 2026-07-25 | fix(deps): loosen dev pins, fix pytest-asyncio>=0.25.0 for pytest 9 compat, drop duplicates |
| [`0cf58cd8`](https://github.com/cirvannaco-png/Nakima/commit/0cf58cd891492c2504d9b0018ab7d5a63558e612) | 2026-07-25 | fix(deps): loosen all version pins to >= minimums to allow pip to resolve freely |
| [`44a91bf7`](https://github.com/cirvannaco-png/Nakima/commit/44a91bf75bd3b3e97435e1c836c006433475c5c9) | 2026-07-24 | fix: bump vulnerable deps to clear all 24 Trivy HIGH findings |
| [`1646bf37`](https://github.com/cirvannaco-png/Nakima/commit/1646bf37221f931c69fb0981241ca226fbfda9fb) | 2026-07-24 | ci: update CI workflow |
| [`3e71ac73`](https://github.com/cirvannaco-png/Nakima/commit/3e71ac738fdb3cea954147166cf17e88b04a6e42) | 2026-07-24 | fix(test): align test with preflight() — missing token is a warning not an error |
| [`0cd0ec8f`](https://github.com/cirvannaco-png/Nakima/commit/0cd0ec8f49b72347453862220557bb29d84501b1) | 2026-07-24 | fix(test): use monkeypatch to clear GITHUB_TOKEN env var in provider-missing-token test |
| [`62d97b38`](https://github.com/cirvannaco-png/Nakima/commit/62d97b389465619993ab5aca49b41ab9c7788830) | 2026-07-24 | ci: replace ci.yml with uploaded version + fix indentation, safety scan, trivy continue-on-error |
| [`84b609eb`](https://github.com/cirvannaco-png/Nakima/commit/84b609eb7e5b8d8981644eb0c566b1fa172582b5) | 2026-07-24 | ci: fix all 50 ruff lint/format errors |
| [`8b7de634`](https://github.com/cirvannaco-png/Nakima/commit/8b7de6343aef6444e2750e367b3128d7c12c93ea) | 2026-07-23 | ci: make bandit non-blocking (continue-on-error) while code is being hardened |
| [`69a54275`](https://github.com/cirvannaco-png/Nakima/commit/69a54275221b4e0a2ac32f8fc8a86f33d3320af7) | 2026-07-23 | ci: add pytest-cov==6.1.0 to requirements-dev.txt |
| [`d72885b2`](https://github.com/cirvannaco-png/Nakima/commit/d72885b29e15268000848abcf1a3b72f57118ede) | 2026-07-23 | ci: upgrade safety 3.5.1→3.8.1 to fix typer.rich_utils crash |
| [`0c30e56f`](https://github.com/cirvannaco-png/Nakima/commit/0c30e56f332f2f399ab693cdc0f162f840f36539) | 2026-07-23 | ci: fix trivy-action version (0.30.0→0.36.0) and safety exit-code 4 handling |
| [`4ff8990c`](https://github.com/cirvannaco-png/Nakima/commit/4ff8990caf55cd8f9b5780923a04993d8ef020d6) | 2026-07-22 | feat: GitHub App manifest registration flow for XO Nakima |
| [`2607c4f5`](https://github.com/cirvannaco-png/Nakima/commit/2607c4f54aeb85587e06c9d8348d896f9050551a) | 2026-07-22 | fix: downgrade missing AI token from startup crash to runtime warning |
| [`99f224ce`](https://github.com/cirvannaco-png/Nakima/commit/99f224ce719641dd058c601a86d095603f0a20a8) | 2026-07-22 | chore: remove Replit workspace scaffolding from repo |
| [`a361fb31`](https://github.com/cirvannaco-png/Nakima/commit/a361fb31fc47c1e41a3dff15f1afa36f34cf27e9) | 2026-07-22 | ci: add code-quality workflow, import smoke tests, git verify step |
| [`fdb14a9d`](https://github.com/cirvannaco-png/Nakima/commit/fdb14a9df71e5162c02946fd417f1c2c7269c7bd) | 2026-07-21 | fix: deprecations, missing dep, OOM upload guard, and datetime safety |
| [`824e9868`](https://github.com/cirvannaco-png/Nakima/commit/824e98686a41ed0127e6d96fb58260fa95a7547a) | 2026-07-21 | fix: production-readiness sweep — CI, NSIL, sandbox, NEIS |
| [`ba8f290e`](https://github.com/cirvannaco-png/Nakima/commit/ba8f290ed9f5b4444c50630f5141c779c61f547a) | 2026-07-21 | fix: resolve 6 bugs from deep-dive audit |
| [`13cc43e2`](https://github.com/cirvannaco-png/Nakima/commit/13cc43e2fa35f602c888bbc75844f11953ac9798) | 2026-07-21 | fix: add git to runtime image and reduce workers to 1 |
| [`b0234e09`](https://github.com/cirvannaco-png/Nakima/commit/b0234e0947b06aa267dd79706e56dca42b8e3caa) | 2026-07-21 | fix(sweep): resolve all critical/high issues found in deep-dive system sweep |
| [`b12e1c10`](https://github.com/cirvannaco-png/Nakima/commit/b12e1c1014caf9455c696ba93bccdcf3d9cbace2) | 2026-07-21 | Add agent memory files for security push and UI tracking |
| [`b729a6d4`](https://github.com/cirvannaco-png/Nakima/commit/b729a6d49eeccdaded0477c649291c8fe15e3b86) | 2026-07-21 | fix: remove --log-config /dev/null from uvicorn CMD (RuntimeError on Render) |
| [`19991f5d`](https://github.com/cirvannaco-png/Nakima/commit/19991f5d2a4b367e52c23519d2ad81bb8361a547) | 2026-07-20 | fix: resolve all pnpm vulnerabilities, remove binary assets from git |
| [`05b4bb5a`](https://github.com/cirvannaco-png/Nakima/commit/05b4bb5a0c2c1c5607ac90e9146f8ee5e6939589) | 2026-07-20 | fix: upgrade esbuild 0.27.3→0.28.1 (GHSA-g7r4-m6w7-qqqr), add Dependabot config, security policy |
| [`a8f50cc1`](https://github.com/cirvannaco-png/Nakima/commit/a8f50cc19a80c7b4c0f927ad93cf484eed9d43e4) | 2026-07-20 | feat: apply EIP patch, rebuild UI, harden security, full doc suite, proprietary licence |
| [`bfefe9fe`](https://github.com/cirvannaco-png/Nakima/commit/bfefe9fe94c77f8c87d51fd13e5cc35a6fea5b4b) | 2026-07-20 | Merge remote changes: resolve .gitignore conflict |
| [`248251e0`](https://github.com/cirvannaco-png/Nakima/commit/248251e070e33abe92d85a46578aa49de3273d51) | 2026-07-20 | Initial commit |
| [`68d7b2e0`](https://github.com/cirvannaco-png/Nakima/commit/68d7b2e03bf3a32395f3d8ff5aaf7dfb4d75ef84) | 2026-07-20 | Delete LICENSE |
| [`f54bb951`](https://github.com/cirvannaco-png/Nakima/commit/f54bb951da09594a1df200f8081b272a637a42ca) | 2026-07-20 | feat: virus scanner, target binding, command centre + production hardening |
| [`9ef05942`](https://github.com/cirvannaco-png/Nakima/commit/9ef059424eece7140fe957722113c6c15cf6060c) | 2026-07-20 | feat: EIP four gates, DAST, documents gateway + launch kit |
| [`32ff81e0`](https://github.com/cirvannaco-png/Nakima/commit/32ff81e05f908eb3319b3e6960167cdf018e37df) | 2026-07-19 | feat: apply patches + fix all audit findings |
| [`90e6fcc1`](https://github.com/cirvannaco-png/Nakima/commit/90e6fcc14499fd6c68892ffdb28070df5738eb3e) | 2026-07-19 | feat: env preflight, JSON structured logs, docker smoke tests, README updates |
| [`fedfdf5b`](https://github.com/cirvannaco-png/Nakima/commit/fedfdf5bb7fb70c46fbf3055df172c16ae1ca593) | 2026-07-18 | feat(providers): add free GitHub Models provider as default |
| [`87e8b86a`](https://github.com/cirvannaco-png/Nakima/commit/87e8b86a95a6c7915652aa206e190e686fd5f6d6) | 2026-07-17 | Merge pull request #1 from cirvannaco-png/dependabot/pip/pip-a7f68e23de |
| [`3f1f93c3`](https://github.com/cirvannaco-png/Nakima/commit/3f1f93c3f4976ad9121d680a6f2df752ac3a8170) | 2026-07-17 | chore: add pre-commit hooks, OpenAPI docs, health probes, lazy GitHub auth |
| [`fe6f1efb`](https://github.com/cirvannaco-png/Nakima/commit/fe6f1efb3dfb096896ec20469ac8e729fc5a7fdd) | 2026-07-17 | Restructure repo: full source, CI, scripts, pyproject, docs |
| [`d42a1525`](https://github.com/cirvannaco-png/Nakima/commit/d42a152535e9f31dce0b24af05fdca6173e4d79b) | 2026-07-16 | Bump the pip group across 1 directory with 2 updates |
| [`0a43e6f2`](https://github.com/cirvannaco-png/Nakima/commit/0a43e6f295fdd69202599d50857568e33f9af0ca) | 2026-07-16 | Unpack nakima.zip into repository root |
| [`6fffe903`](https://github.com/cirvannaco-png/Nakima/commit/6fffe9036f3b3f50a09dc1400f89021ad51d3257) | 2026-07-15 | Update issue templates |
| [`34bb6d93`](https://github.com/cirvannaco-png/Nakima/commit/34bb6d93bdbc83df0a78d48c7a10d512ac0cb91d) | 2026-07-15 | Create manual.yml |
| [`500034c0`](https://github.com/cirvannaco-png/Nakima/commit/500034c0cca285922f77e4285a00db142744be51) | 2026-07-15 | Add files via upload |
| [`d44f4ea6`](https://github.com/cirvannaco-png/Nakima/commit/d44f4ea61964631dab205e249ff12c18c652a150) | 2026-07-15 | Initial commit |

---

## License

Nakima is **proprietary software**. Source code is available for audit only.
You may **not** copy, host, or redistribute it. See [LICENSE](LICENSE).

The hosted GitHub App (once launched) is available under separate Terms of Service.
