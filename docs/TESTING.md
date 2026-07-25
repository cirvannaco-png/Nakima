# Nakima Testing Guide

## Running Tests

```bash
# Full test suite
pytest

# With coverage
pytest --cov=. --cov-report=term-missing

# Single module
pytest tests/test_security_nsil.py -v

# Fast (skip slow integration tests)
pytest -m "not slow"
```

## Test Structure

```
tests/
├── conftest.py                    # Shared fixtures (in-memory SQLite, tmp repos)
├── test_dast.py                   # DAST scanner
├── test_documents.py              # Document upload/parse pipeline
├── test_github_models_provider.py # GitHub Models AI provider
├── test_intelligence.py           # Decision registry + event log
├── test_pentest_simulator.py      # Pentest simulation checks
├── test_preflight_and_logging.py  # Config preflight, structured logging
├── test_quality_gate.py           # Quality gate verdicts
├── test_reasoning.py              # NEIS reasoning engines
├── test_reports.py                # PDF report generation
├── test_security_nsil.py          # NSIL orchestration (all scanners)
├── test_ssrf_guard.py             # SSRF guard blocklist
├── test_target_binding.py         # GitHub ownership binding
├── test_virus_scanner.py          # ClamAV scanner (mocked)
└── test_workflow_security_gate.py # Workflow security gate
```

## Key Test Fixtures (`conftest.py`)

| Fixture | Description |
|---|---|
| `db_session` | Async SQLAlchemy session backed by in-memory SQLite |
| `tmp_path` | Temporary directory (pytest built-in) for fake repos |
| `monkeypatch` | Pytest built-in for patching |

Tests use SQLite (`aiosqlite`) instead of PostgreSQL to avoid requiring a running database during local development. CI uses real PostgreSQL (see `.github/workflows/ci.yml`).

## Coverage Requirements

- CI enforces **60% minimum coverage** (`--cov-fail-under=60`)
- The QualityGate enforces that source file changes are accompanied by test file changes
- New security scanners require corresponding test coverage

## Writing Tests

### Async tests

All test functions using `async/await` are automatically handled by `pytest-asyncio` (`asyncio_mode = "auto"` in `pyproject.toml`).

```python
async def test_my_feature(db_session, tmp_path):
    # db_session is already an open async session
    ...
```

### Mocking outbound calls

Never make real outbound network calls in tests. Use `monkeypatch` to replace `httpx.AsyncClient` or specific functions:

```python
def _patch_client(monkeypatch, responses):
    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url, **kw):
            return responses.pop(0)

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kw: _MockClient())
```

### Mocking SecurityAgent (Docker dependency)

Tests that exercise NSIL skip agent-based scanners (SAST/deps) by patching `SecurityAgent` to raise, then calling `scan(..., include_agent_scanners=False)`.

## CI Test Matrix

See `.github/workflows/ci.yml`:
- Lint (ruff + flake8)
- SAST (bandit)
- Dependency audit (safety)
- Tests with coverage (against PostgreSQL 16)
- Docker build (app + sandbox images)
- Container scan (Trivy)