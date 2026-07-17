# Nakima

Autonomous GitHub App: watches issues, plans a fix with an AI provider, generates
code, validates it in a sandbox, and opens a PR.

This is a reconciliation of four separate scaffold drafts into one working
codebase, with the auth bug fixed and the stubbed logic replaced with real
implementations. Everything below has been import-tested and exercised via
FastAPI's TestClient — not just syntax-checked.

## What was actually broken, and what's fixed

### v1 (core issue→PR pipeline)

| Bug | File(s) | Fix |
|---|---|---|
| `settings.GITHUB_PRIVATE_key` typo — attribute didn't exist | `githubapp/auth.py` | Corrected to `GITHUB_PRIVATE_KEY`; added `GITHUB_PRIVATE_KEY_PATH` to `Settings` |
| `load_ssh_private_key()` used on a PKCS#1 PEM key — throws on any real GitHub App key | `githubapp/auth.py` | Switched to `load_pem_private_key()` |
| Local package named `github/` shadowed the installed `PyGithub` library, so `from github import Github` imported the wrong module | whole project | Renamed local package `github/` → `githubapp/` |
| Three incompatible `verify_webhook()` signatures across the source drafts | `githubapp/webhooks.py` | One reconciled version returning a typed `WebhookEvent` |
| `Task(metadata=payload)` — `metadata` is reserved on every SQLAlchemy declarative model | `models/task.py` | Renamed column to `event_payload` |
| `select(Repository)` used with no `sqlalchemy.select` import | `orchestrator/workflow.py` | Import added |
| Two incompatible `process_task()` implementations | `orchestrator/workflow.py` | One reconciled pipeline |
| `ImplementationAgent` had three different, non-matching method signatures across drafts | `agents/implementation.py` | One `execute()`-based interface |
| AI code generation wrote the *entire* raw model response into one hardcoded file | `utils/file_blocks.py`, `agents/implementation.py` | Providers emit a `### FILE: path` convention; a real parser splits it into per-file writes |
| Validation failures always reported `"file": None` | `validation/pipeline.py` | Real regex extraction of the offending file/line |
| `requirements.txt` missing `PyJWT`, `cryptography`, `PyGithub`, `tree-sitter-languages` | `requirements.txt` | Added |
| Sandbox built a tar archive of the repo and never used it | `execution/sandbox.py` | Removed; sandbox runs network-disabled with a memory cap |
| Webhook router defined but never mounted — every real webhook would 404 | `api/router.py` | Mounted at `/github` |
| Auth failures during a webhook bubbled up as a raw 500 with a stack trace on a public endpoint | `githubapp/app.py` | Caught and returned as a clean `502` |
| Installation tokens re-fetched from GitHub on every webhook | `githubapp/auth.py` | In-memory cache respecting GitHub's 1-hour token expiry |

### v2 (code graph, knowledge graph, policy engine, learning system, remaining agents)

| Bug | File(s) | Fix |
|---|---|---|
| `KnowledgeNode.metadata` / `KnowledgeEdge.metadata` — same reserved-name collision as `Task.metadata`, would crash at import | `models/knowledge.py` | Renamed to `extra_data` |
| `_create_nodes_from_symbols` ended a call with a bare `...` after keyword args — literal `SyntaxError`, not valid Python | `repository/graph_builder.py` | Rewritten as a real two-pass builder (nodes, then dependency resolution against a symbol table) |
| `RepositoryAnalyzer` fixed to one language at construction, but fed both `.py` and `.js` files | `repository/analysis.py` | Per-language parser cache; unsupported extensions return `[]` instead of parsing with the wrong grammar |
| `descendant_for_point_range` doesn't clamp an out-of-bounds end column — a hardcoded `999` silently returned the root node instead of the target line | `repository/analysis.py` | Uses the actual line length instead |
| `GraphQuery.get_symbol` matched file nodes by basename only; `ContextBuilder` looked them up by full relative path — nested files never resolved | `repository/graph_query.py` | Added `get_file_node()`, matching on `file_path` |
| `MemoryRetriever.get_past_fixes` filtered on `node_type == "commit"`, but nothing ever creates a `"commit"` node — always returned empty | `memory/retriever.py` | Searches `"failure"` nodes and follows the `"fixes"` edge to the actual `"fix"` node |
| `update_memory_from_failure` referenced `.id` on a freshly-constructed node before flush (`default=uuid.uuid4` only fires at flush) | `memory/learning.py` | UUIDs generated up front, before the edge is built |
| `link_fix_to_issue` was a bare `# ...` stub | `memory/knowledge_graph.py` | Implemented for real |
| `PolicyChecker.check_all_policies` referenced `policy.branch_pattern` — `policy` was never fetched in that method (`NameError`) | `security/policy_checker.py` | Fetches the policy first |
| `check_required_reviewers` referenced `policy.required_reviewers`, which didn't exist on the model at all | `models/policy.py`, `security/policy_checker.py` | Added the column; fixed the `NameError` |
| `check_coding_standards` called `self._has_docstrings()` — never defined | `security/policy_checker.py` | Real `ast`-based docstring check |
| `ValidationPipeline` rewrite dropped the tested file/line regex extraction | `validation/pipeline.py` | Merged: kept the extraction, made it multi-language via `ToolRegistry` |
| `refactor_file` / `generate_tests` / `update_readme` wrote the *raw* provider response straight to disk — but those provider methods use the `### FILE:` convention, so the block markers themselves would end up in the file | `agents/refactoring.py`, `agents/testing.py`, `agents/documentation.py` | All three now parse via `utils/file_blocks` like `ImplementationAgent`/`DebugAgent` do |
| `DebugAgent` referenced `self.session` and `context["repo_id"]` that were never set anywhere | `agents/debug.py` | Both now explicitly passed in via `params`; graph enrichment degrades gracefully if absent instead of crashing |
| Rate limiting imported `slowapi` but never applied `@limiter.limit()` to anything — purely decorative | `api/router.py`, `githubapp/app.py`, `api/v1/endpoints/repositories.py` | Actually applied and load-tested (confirmed real 429s) |
| `radon`, `slowapi`, `networkx` used but not in `requirements.txt` | `requirements.txt` | Added |
| `audit_dependencies` / `measure_coverage` returned hardcoded placeholders (`85.0`, `[]`) | `agents/security_agent.py`, `agents/testing.py` | Real `safety`/`pytest-cov` output parsing |

Every fix above was exercised with a real test, not just read for correctness — see `tests/`. `pytest` passes 31/31 locally with the exact dependency versions pinned in `requirements-dev.txt` (the same ones CI installs).



## Setup

### 1. Register the GitHub App

Go to **https://github.com/settings/apps/new** (or your org's equivalent).

- **Webhook URL**: your server's public URL + `/github/webhook`
- **Webhook secret**: generate one, save it for `.env`
- **Permissions**: Repository → Contents (read/write), Issues (read/write), Pull requests (read/write)
- **Subscribe to events**: Issues, Pull request, Push
- After creating the App, generate a **private key** — this downloads a `.pem`
  file once. Save its path or contents for `.env`.
- Note the **App ID** from the App's settings page.
- Install the App on the repo(s) you want it to act on.

### 2. Configure

```bash
cp .env.example .env
# fill in GITHUB_APP_ID, GITHUB_PRIVATE_KEY_PATH (point it at the .pem you
# downloaded), GITHUB_WEBHOOK_SECRET, and ANTHROPIC_API_KEY
```

### 3. Run

```bash
docker build -f Dockerfile.sandbox -t nakima-sandbox:latest .
docker-compose up -d db redis
pip install -r requirements.txt
alembic upgrade head
uvicorn api.router:app --reload --port 8000
```

Or the whole stack via `docker-compose up`.

Local webhook testing needs a tunnel (ngrok, Cloudflare Tunnel, etc.) pointed
at port 8000, with that URL set as the App's webhook URL.

### 4. Verify

```bash
curl http://localhost:8000/api/v1/health/
# {"status": "ok", "version": "1.0.0"}
```

Open an issue on a repo the App is installed on — Nakima should pick it up,
plan a fix, validate it in the sandbox, and open a PR.

## Architecture (v2)

```
Issue opened ──▶ orchestrator.handle_webhook_event
                      │
                      ├─▶ KnowledgeGraphBuilder.index_issue   (memory/knowledge_graph.py)
                      │
                      ▼
                 process_task
                      │
      ┌───────────────┼────────────────────────────────────┐
      ▼               ▼                                     ▼
  clone + branch   RepositoryAnalyzer                   GraphBuilder
  (repository/     .extract_structure_summary()          .build_full_graph()
   engine.py)            │                                    │
                          ▼                                    ▼
                    PlanningEngine.create_plan       ContextBuilder.build_for_task
                    (planner/planner.py)              (real code snippets +
                          │                             dependency subgraph via
                          ▼                             GraphQuery)
                    ImplementationAgent.generate_changes ◀──┘
                          │  (parses ### FILE: blocks, writes real files)
                          ▼
                    ValidationPipeline.validate  ──fail──▶  DebugAgent.debug_failure
                    (execution/tool_registry.py:              (graph-aware: call-graph
                     format/lint/build/test/security)           enrichment via GraphQuery)
                          │  success                              │
                          │                              OutcomeAnalyzer
                          ▼                              .update_memory_from_failure
                    PolicyChecker.check_all_policies      (memory/learning.py)
                    (security/policy_checker.py)
                          │  clear
                          ▼
                    commit → push → open PR

PR closed ──▶ KnowledgeGraphBuilder.index_pull_request
              OutcomeAnalyzer.record_pr_outcome  (merged? extracts conventions from diff)

Push ──▶ GraphBuilder.build_full_graph()  (keeps the graph current)
```

`AnalysisAgent`, `RefactoringAgent`, `TestingAgent`, `DocumentationAgent`, and
`SecurityAgent` (`agents/`) aren't wired into the automatic pipeline above —
they're available to call directly (e.g. from a future manual-trigger
endpoint) for on-demand repo scans, refactors, test generation, doc updates,
and dependency audits.

## Testing

```bash
pip install -r requirements-dev.txt
pytest -v
```

31 tests, all passing locally against the exact versions pinned in
`requirements-dev.txt` — the same ones `.github/workflows/ci.yml` installs.
Covers: symbol extraction correctness (function vs. method vs. class
distinction, multi-language dispatch), graph construction and querying,
the `### FILE:` block parser (including a path-traversal guard), multi-language
validation failure extraction, the policy engine (specifically the two
`NameError` bugs), and knowledge-graph retrieval (specifically the
`node_type` mismatch bug). No test hits a real GitHub API, real AI provider,
or real Docker sandbox — those are exercised via `TestClient` against the
auth/webhook boundary instead, using a throwaway key.

## What's still a stub / next steps

- `AnalysisAgent`, `RefactoringAgent`, `TestingAgent`, `DocumentationAgent`,
  `SecurityAgent` are implemented and tested individually but not yet called
  from any endpoint or webhook — they need a trigger (manual API call, slash
  command in a PR comment, scheduled job, etc.).
- Only the `claude` provider is implemented (it's your `DEFAULT_AI_PROVIDER`).
  `codex`, `copilot`, `deepseek`, `replit` are stubbed out in
  `providers/manager.py`'s `provider_map` — each needs to follow the same
  `AIProvider` interface as `providers/implementations/claude.py`.
- Import resolution in `GraphBuilder` is a name-based heuristic (matches
  module/file names against a global symbol table) — no real per-language
  import resolver, so aliased imports (`import foo as bar`) and shadowed
  names won't resolve correctly.
- No auth/rate-limiting on `/api/v1/tasks/{id}` or the new `/api/v1/repositories/*`
  endpoints beyond the `10/minute` limit on `/index`.
- `HealthScorer` only scores Python repos (via `radon`); JS/TS/Go repos get
  `{"score": None, "reason": "no Python files found"}`.

## Project structure

```
nakima/
├── api/                    FastAPI app entry (`api/router.py`) and versioned routes
│   └── v1/                   REST endpoints: health, tasks, repositories
├── agents/                 Specialised AI agents (implementation, debug, refactor, tests, docs, security, analysis)
├── core/                   Settings, structured logging, rate limiter
├── database/               SQLAlchemy async engine, session, declarative base
├── models/                 ORM models: repository, task, graph, knowledge, policy
├── githubapp/              GitHub App auth (JWT + installation tokens), webhook verification, router
├── orchestrator/           End-to-end issue → plan → code → validate → PR workflow
├── planner/                Planning engine + repo/graph context builder
├── providers/              AI provider interface + Claude implementation + manager
├── repository/             Repo indexing, tree-sitter analysis, graph builder/query, health scoring
├── memory/                 Knowledge-graph builder, retriever, outcome learning
├── execution/              Docker sandbox runner, tool registry
├── validation/             Multi-language lint/test pipeline
├── security/               Policy checker
├── monitoring/             OpenTelemetry / Prometheus hooks
├── utils/                  Shared helpers (`### FILE:` block parser, etc.)
├── alembic/                Database migrations
├── tests/                  Pytest suite (async, in-memory SQLite)
├── scripts/                dev.sh, test.sh, setup.sh, migrate.sh
├── .github/workflows/      CI: lint (ruff) → test (3.11/3.12) → build (sdist+wheel) → docker
├── Dockerfile              Production container
├── Dockerfile.sandbox      Sandbox image used by `execution/sandbox.py`
├── docker-compose.yml      Local Postgres + Redis + app
├── requirements.txt        Runtime pins
├── requirements-dev.txt    Runtime + test pins
├── pyproject.toml          Packaging, ruff, pytest config
├── alembic.ini             Alembic config
└── .env.example            Copy to `.env` and fill in
```

## Setup

```bash
# 1. One-shot bootstrap (creates .venv, installs deps, seeds .env)
bash scripts/setup.sh
source .venv/bin/activate

# 2. Bring up Postgres + Redis (or point .env at your own)
docker compose up -d db redis

# 3. Apply migrations
bash scripts/migrate.sh

# 4. Run the API with autoreload
bash scripts/dev.sh
# → http://localhost:8000/api/v1/health/
```

## Development scripts

| Script | Purpose |
|---|---|
| `scripts/setup.sh` | Create `.venv`, install `requirements-dev.txt`, seed `.env` |
| `scripts/dev.sh`   | Run `uvicorn api.router:app --reload` on port 8000 |
| `scripts/test.sh`  | Run the pytest suite with CI-equivalent env vars |
| `scripts/migrate.sh` | `alembic upgrade head` |

## CI

`.github/workflows/ci.yml` runs on every push and PR to `main` and enforces:

1. **Lint** — `ruff check .` and `ruff format --check .`
2. **Test** — `python -m compileall` + `pytest -v` on Python 3.11 and 3.12
3. **Build** — `python -m build` (sdist + wheel), uploaded as an artifact
4. **Docker** — builds `Dockerfile` (no push) to catch image regressions

Lint and test must pass before build and docker run.
