from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Base
    APP_NAME: str = "nakima"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"

    # Database
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "nakima"
    DB_PASSWORD: str = "nakima"
    DB_NAME: str = "nakima"
    DB_POOL_SIZE: int = 20
    DATABASE_URL: str | None = None

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_URL: str | None = None

    # GitHub App (webhook / PR automation)
    # A GitHub App private key comes from GitHub as a downloaded .pem file (PKCS#1 RSA).
    # Provide EITHER the raw PEM contents (GITHUB_PRIVATE_KEY) OR a path to the .pem file
    # (GITHUB_PRIVATE_KEY_PATH). The path is easier to manage in most deployments.
    GITHUB_APP_ID: str | None = None
    GITHUB_PRIVATE_KEY: str | None = None
    GITHUB_PRIVATE_KEY_PATH: str | None = None
    GITHUB_WEBHOOK_SECRET: str = ""

    # AI Providers
    # Default: GitHub Models (free, no separate account, uses a GitHub PAT).
    DEFAULT_AI_PROVIDER: str = "github"
    PROVIDER_MAX_RETRIES: int = 3
    PROVIDER_TIMEOUT: int = 300

    # GitHub Models — free inference via https://models.github.ai/inference.
    # Create a fine-grained PAT with "Models: read" at
    # https://github.com/settings/personal-access-tokens/new and set it as
    # GITHUB_TOKEN. GITHUB_MODELS_TOKEN can override it if you want to use a
    # different token for inference than for repo automation.
    GITHUB_TOKEN: str | None = None
    GITHUB_MODELS_TOKEN: str | None = None
    GITHUB_MODELS_MODEL: str = "openai/gpt-4o-mini"

    # Optional paid providers.
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    DEEPSEEK_API_KEY: str | None = None

    # Execution
    EXECUTION_MAX_RETRIES: int = 2
    TEST_TIMEOUT: int = 600
    BUILD_TIMEOUT: int = 1200
    SANDBOX_IMAGE: str = "nakima-sandbox:latest"

    # Security
    SCAN_ON_PR: bool = True
    SECRET_DETECTION: bool = True

    # NEIS (neis/analyzers/tech_scout.py) — outbound calls to PyPI/npm to
    # check current upstream versions. Short timeout + low retry count on
    # purpose: a slow/unreachable registry should degrade one package's
    # intel to "unknown", not stall the whole evolution run.
    NEIS_HTTP_TIMEOUT: float = 5.0
    NEIS_HTTP_MAX_RETRIES: int = 1

    # Engineering Intelligence Reports (reports/pdf_generator.py). Local disk
    # for now — there's no object-storage abstraction anywhere else in this
    # codebase either, and adding one just for reports would be exactly the
    # kind of unjustified complexity Backend Forge's Cardinal Rule warns
    # against. Swap for S3/GCS-backed storage if/when Nakima needs reports
    # to survive a redeploy of an ephemeral filesystem — same tradeoff
    # already discussed for Cirvanna's Hugging Face Spaces vs. GCE decision.
    REPORTS_DIR: str = "./reports_output"

    # Virus scanning (security/virus_scanner.py) via a ClamAV clamd daemon.
    # None (the default) means no scanner is reachable — uploads and repo
    # scans proceed without a virus check, and that fact is recorded
    # honestly (ProjectDocument.virus_scan_status = "unavailable",
    # SecurityIntelligenceLayer reports "virus" in scanners_skipped)
    # rather than silently treated as "scanned and clean". Set CLAMD_HOST
    # to enable it — see security/virus_scanner.py's docstring for the
    # deployment steps (clamd + freshclam) this actually requires.
    CLAMD_HOST: str | None = None
    CLAMD_PORT: int = 3310
    CLAMD_TIMEOUT_SECONDS: float = 15.0

    # Logging: "json" (default, structured) or "text" (human-readable dev logs).
    LOG_FORMAT: str = "json"

    class Config:
        env_file = ".env"
        extra = "allow"

    def model_post_init(self, __context) -> None:
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )
        if not self.REDIS_URL:
            self.REDIS_URL = f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


settings = Settings()


# --- Runtime preflight -----------------------------------------------------


class PreflightError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def preflight(s: "Settings | None" = None) -> list[str]:
    """Validate that required env vars are present for the active environment.

    Returns the list of warning strings (non-fatal). Raises PreflightError
    when a required value is missing.
    """
    s = s or settings
    errors: list[str] = []
    warnings: list[str] = []

    # AI provider credential check — warning only, not a hard error.
    # The application can still serve webhooks, the health endpoint, repository
    # management, and any non-AI workflow steps without a token. AI-backed
    # features (CognitiveEngine, SecurityAgent, etc.) will fail at call-time
    # with a clear error rather than preventing the whole process from starting.
    # This matches how other optional integrations (ClamAV, GitHub App) are
    # handled: degrade gracefully, don't refuse to boot.
    provider = (s.DEFAULT_AI_PROVIDER or "").lower()
    if provider == "github":
        if not (s.GITHUB_MODELS_TOKEN or s.GITHUB_TOKEN):
            warnings.append(
                "DEFAULT_AI_PROVIDER=github but neither GITHUB_MODELS_TOKEN "
                "nor GITHUB_TOKEN is set — AI-backed features will be unavailable."
            )
    elif provider == "claude":
        if not s.ANTHROPIC_API_KEY:
            warnings.append(
                "DEFAULT_AI_PROVIDER=claude but ANTHROPIC_API_KEY is missing — AI-backed features will be unavailable."
            )
    elif provider == "openai":
        if not s.OPENAI_API_KEY:
            warnings.append(
                "DEFAULT_AI_PROVIDER=openai but OPENAI_API_KEY is missing — AI-backed features will be unavailable."
            )
    elif provider == "deepseek":
        if not s.DEEPSEEK_API_KEY:
            warnings.append(
                "DEFAULT_AI_PROVIDER=deepseek but DEEPSEEK_API_KEY is missing — AI-backed features will be unavailable."
            )

    # If a key path is given, verify the file actually exists before treating
    # it as "provided" — a missing file fails at JWT-signing time, not here.
    if s.GITHUB_PRIVATE_KEY_PATH:
        import os  # noqa: PLC0415

        if not os.path.isfile(s.GITHUB_PRIVATE_KEY_PATH):
            errors.append(
                f"GITHUB_PRIVATE_KEY_PATH={s.GITHUB_PRIVATE_KEY_PATH!r} does not exist or is not a regular file."
            )

    # GitHub App: optional overall, but if partly set, all three must be present.
    app_bits = [s.GITHUB_APP_ID, (s.GITHUB_PRIVATE_KEY or s.GITHUB_PRIVATE_KEY_PATH), s.GITHUB_WEBHOOK_SECRET]
    if any(app_bits) and not all(app_bits):
        errors.append(
            "GitHub App is partially configured: set GITHUB_APP_ID, "
            "GITHUB_PRIVATE_KEY (or GITHUB_PRIVATE_KEY_PATH), and "
            "GITHUB_WEBHOOK_SECRET together — or leave them all unset."
        )
    elif not any(app_bits):
        warnings.append(
            "GitHub App not configured — webhook endpoints will reject requests. "
            "Set GITHUB_APP_ID/GITHUB_PRIVATE_KEY/GITHUB_WEBHOOK_SECRET to enable."
        )

    if s.ENVIRONMENT == "production":
        if s.DB_PASSWORD in ("", "nakima", "changeme"):
            errors.append("ENVIRONMENT=production but DB_PASSWORD is a default/empty value.")
        if not s.GITHUB_WEBHOOK_SECRET:
            errors.append("ENVIRONMENT=production requires GITHUB_WEBHOOK_SECRET.")

    if errors:
        raise PreflightError("Configuration preflight failed:\n  - " + "\n  - ".join(errors))
    return warnings
