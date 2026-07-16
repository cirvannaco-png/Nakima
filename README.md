# Nakima

Autonomous GitHub App: watches issues, plans a fix with an AI provider, generates
code, validates it in a sandbox, and opens a PR.

This is a reconciliation of four separate scaffold drafts into one working
codebase, with the auth bug fixed and the stubbed logic replaced with real
implementations. Everything below has been import-tested and exercised via
FastAPI's TestClient — not just syntax-checked.

## What was actually broken, and what's fixed

| Bug | File(s) | Fix |
|---|---|---|
| `settings.GITHUB_PRIVATE_key` typo — attribute didn't exist | `githubapp/auth.py` | Corrected to `GITHUB_PRIVATE_KEY`; added `GITHUB_PRIVATE_KEY_PATH` to `Settings` |
| `load_ssh_private_key()` used on a PKCS#1 PEM key — throws on any real GitHub App key | `githubapp/auth.py` | Switched to `load_pem_private_key()` |
| Local package named `github/` shadowed the installed `PyGithub` library, so `from github import Github` imported the wrong module | whole project | Renamed local package `github/` → `githubapp/` |
| Three incompatible `verify_webhook()` signatures across the source drafts | `githubapp/webhooks.py` | One reconciled version returning a typed `WebhookEvent` |
| `Task(metadata=payload)` — `metadata` is reserved on every SQLAlchemy declarative model | `models/task.py` | Renamed column to `event_payload` |
| `select(Repository)` used with no `sqlalchemy.select` import | `orchestrator/workflow.py` | Import added |
| Two incompatible `process_task()` implementations | `orchestrator/workflow.py` | One reconciled pipeline: plan → clone → generate → validate/retry → commit → push → PR |
| `ImplementationAgent` had three different, non-matching method signatures across drafts | `agents/implementation.py` | One `execute()`-based interface |
| AI code generation wrote the *entire* raw model response into one hardcoded `nakima_generated.py`, regardless of how many files should have changed | `utils/file_blocks.py`, `agents/implementation.py` | Providers now emit a `### FILE: path` convention; a real parser splits it into per-file writes (handles multiple files, nested dirs, and deletions) |
| Validation failures always reported `"file": None` — the debug agent had nothing to act on | `validation/pipeline.py` | Real regex extraction of the offending file/line from flake8, pytest, and black output |
| `requirements.txt` missing `PyJWT`, `cryptography`, `PyGithub`, `tree-sitter-languages` despite the code importing them | `requirements.txt` | Added |
| Dead code: sandbox built a tar archive of the repo and never used it | `execution/sandbox.py` | Removed; sandbox now runs network-disabled with a memory cap |
| `github/app.py`'s router was defined but never mounted into the FastAPI app — every real webhook would 404 | `api/router.py` | Mounted at `/github` |
| Auth failures during a webhook bubbled up as a raw 500 with a full stack trace on a public endpoint | `githubapp/app.py` | Caught and returned as a clean `502` |
| Installation tokens were re-fetched from GitHub on every webhook with no caching | `githubapp/auth.py` | In-memory cache respecting GitHub's 1-hour token expiry |

Only the `claude` provider is implemented (it's your `DEFAULT_AI_PROVIDER`).
`codex`, `copilot`, `deepseek`, `replit` are stubbed out in `providers/manager.py`
with a `provider_map` you can extend — each just needs to follow the same
`AIProvider` interface as `providers/implementations/claude.py`.

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

## What's still a stub / next steps

- `pull_request` and `push` webhook events are received and acknowledged but
  not acted on yet (`orchestrator/workflow.py` has the `elif` branches ready).
- Only one AI provider is wired up (Claude). Adding another means implementing
  `AIProvider` in `providers/implementations/<name>.py` and registering it in
  `providers/manager.py`'s `provider_map`.
- `agents/refactoring.py`, `agents/testing.py`, `agents/documentation.py`,
  `agents/security_agent.py` exist as concepts in the original drafts but
  weren't reconciled in this pass — only `ImplementationAgent` and
  `DebugAgent` (the two the core issue→PR pipeline actually uses) were built out.
- No auth/rate-limiting on the `/api/v1/tasks/{id}` status endpoint yet.
