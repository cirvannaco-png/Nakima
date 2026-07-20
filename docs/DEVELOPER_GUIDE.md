# Nakima Developer Guide

## Development Setup

### Prerequisites

- Python 3.12+
- Docker (for sandbox + ClamAV)
- PostgreSQL 16 (or use Docker Compose)

### Local setup (without Docker)

```bash
git clone https://github.com/cirvannaco-png/Nakima.git
cd Nakima

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies (including dev tools)
pip install -r requirements.txt -r requirements-dev.txt

# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Configure environment
cp .env.example .env
# Edit .env — at minimum set GITHUB_TOKEN and DATABASE_URL

# Start PostgreSQL (Docker)
docker compose up db -d

# Run migrations
alembic upgrade head

# Start the development server
uvicorn api.router:app --reload --port 8000
```

### Full stack (Docker)

```bash
docker compose up --build
```

---

## Project Structure

```
nakima/
├── agents/         # AI agents (analysis, implementation, code review, …)
├── alembic/        # Database migrations
├── api/            # FastAPI application, routers, request/response schemas
├── core/           # Settings (pydantic-settings), logging, rate limiting
├── database/       # SQLAlchemy session, base model
├── documents/      # Project document upload: gateway, parsers, validators
├── execution/      # Docker sandbox executor and tool registry
├── githubapp/      # GitHub App auth and webhook handler
├── intelligence/   # Decision registry and event log
├── memory/         # Knowledge graph and learning
├── models/         # SQLAlchemy ORM models
├── monitoring/     # OpenTelemetry + Prometheus instrumentation
├── neis/           # NEIS reasoning engines and analyzers
├── orchestrator/   # Workflow pipeline (issue → PR)
├── planner/        # Issue-to-plan decomposition
├── providers/      # AI provider adapters (GitHub Models, Claude, OpenAI)
├── quality/        # Quality gate
├── reports/        # PDF report generation (reportlab)
├── repository/     # Git engine, AST analysis, health scoring
├── security/       # NSIL, DAST, pentest simulator, secret scanner, …
├── static/         # Command Centre dashboard (command-center.html)
├── tests/          # Test suite
├── utils/          # Shared utilities
└── validation/     # Validation pipeline
```

---

## Coding Standards

- **Python 3.12+** — use type hints everywhere; `X | Y` union syntax, `match` statements
- **Ruff** for linting and formatting (configured in `pyproject.toml`)
- **Line length:** 120 characters
- **No `console.log` / `print`** in application code — use `logging.getLogger(__name__)`
- **Async throughout** — all database operations and external calls must be `async/await`
- **Pydantic models** for all API request/response schemas (in `api/schemas.py`)
- **No bare `except:`** — always catch specific exceptions
- **No hardcoded secrets** — all credentials from `core/config.py:Settings`

---

## Adding a New AI Provider

1. Create `providers/myprovider.py` implementing `providers/base.py:BaseProvider`
2. Register it in `providers/__init__.py`
3. Add the provider name to `core/config.py:Settings.DEFAULT_AI_PROVIDER` choices
4. Add any required API key to `core/config.py:Settings` and `.env.example`
5. Write tests in `tests/test_myprovider.py`

---

## Adding a New Security Scanner

1. Create `security/myscanner.py` with an async `scan(repo_dir: Path) -> list[Finding]` interface
2. Add it to `security/nsil.py:SecurityIntelligenceLayer.scan()` in the appropriate sequence
3. Add it to `models/security.py` fingerprinting if findings need regression tracking
4. Write tests (mock all outbound calls)

---

## Database Migrations

```bash
# After modifying a model in models/
alembic revision --autogenerate -m "describe the change"

# Review the generated file in alembic/versions/ — always review before running!
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

Migration files are numbered sequentially (`0001_`, `0002_`, …). Do not rename them.

---

## Branching and PR Workflow

| Branch | Purpose |
|---|---|
| `main` | Production-ready code |
| `develop` | Integration branch |
| `feature/<name>` | Feature work |
| `fix/<name>` | Bug fixes |
| `nakima/issue-*` | Branches opened by Nakima itself |

1. Fork → feature branch → tests → `ruff check .` → PR to `develop`
2. CI must pass (lint, SAST, tests, Docker build)
3. At least one review before merge
4. Squash merge into `develop`; merge `develop` into `main` for releases

---

## Running the Test Suite

```bash
# All tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Specific file
pytest tests/test_security_nsil.py -v

# Watch mode (requires pytest-watch)
ptw tests/
```

Tests use in-memory SQLite (`aiosqlite`) — no running database required. See [TESTING.md](TESTING.md) for the full guide.

---

## Pre-commit Hooks

```bash
# Install
pre-commit install

# Run manually on all files
pre-commit run --all-files
```

Hooks configured in `.pre-commit-config.yaml`: ruff, trailing-whitespace, end-of-file-fixer, check-yaml, check-merge-conflict.

---

## Contributing

By submitting a pull request you agree to the Contributor License Agreement in [LICENSE](../LICENSE). All contributions become subject to the Nakima Proprietary License.
