"""Smoke test: verify the application imports without errors.

Catches broken imports, missing dependencies, and bad module-level code
before any of them reach a deployment. Runs in CI without a database or
live GitHub credentials — if this test fails, nothing else will work.
"""


def test_application_imports():
    """Core FastAPI app and router must be importable."""
    from api.router import app

    assert app is not None


def test_settings_importable():
    """Settings object must load without raising (env vars have CI defaults)."""
    from core.config import settings

    assert settings is not None


def test_models_importable():
    """All ORM models must import cleanly (catches missing FK targets, etc.)."""
    from models.repository import Repository
    from models.task import Task

    assert Repository is not None
    assert Task is not None
