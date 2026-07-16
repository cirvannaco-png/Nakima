from typing import Optional
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

    # GitHub App
    # A GitHub App private key comes from GitHub as a downloaded .pem file (PKCS#1 RSA).
    # Provide EITHER the raw PEM contents (GITHUB_PRIVATE_KEY) OR a path to the .pem file
    # (GITHUB_PRIVATE_KEY_PATH). The path is easier to manage in most deployments.
    GITHUB_APP_ID: Optional[str] = None
    GITHUB_PRIVATE_KEY: Optional[str] = None
    GITHUB_PRIVATE_KEY_PATH: Optional[str] = None
    GITHUB_WEBHOOK_SECRET: str = ""

    # AI Providers
    DEFAULT_AI_PROVIDER: str = "claude"
    PROVIDER_MAX_RETRIES: int = 3
    PROVIDER_TIMEOUT: int = 300
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None

    # Execution
    EXECUTION_MAX_RETRIES: int = 2
    TEST_TIMEOUT: int = 600
    BUILD_TIMEOUT: int = 1200
    SANDBOX_IMAGE: str = "nakima-sandbox:latest"

    # Security
    SCAN_ON_PR: bool = True
    SECRET_DETECTION: bool = True

    class Config:
        env_file = ".env"
        extra = "allow"

    def model_post_init(self, __context) -> None:
        if not self.DATABASE_URL:
            self.DATABASE_URL = (
                f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )
        if not self.REDIS_URL:
            self.REDIS_URL = f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


settings = Settings()
