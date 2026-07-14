"""Application configuration.

All settings are loaded from environment variables (or a local .env file) and
validated by pydantic-settings. Import the singleton via ``from app.core.config
import settings``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -------------------------------------------------------
    PROJECT_NAME: str = "AITraderPro"
    VERSION: str = "0.1.0"
    ENVIRONMENT: Literal["local", "test", "staging", "production"] = "local"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000

    # --- Security ----------------------------------------------------------
    SECRET_KEY: str = Field(
        default="change-me-in-production-please-use-a-64-char-random-string",
        min_length=32,
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    PASSWORD_MIN_LENGTH: int = 8

    # --- CORS --------------------------------------------------------------
    CORS_ORIGINS: list[str] = ["http://localhost:8501", "http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # --- Database ----------------------------------------------------------
    POSTGRES_USER: str = "aitrader"
    POSTGRES_PASSWORD: str = "aitrader"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "aitraderpro"
    DATABASE_URL: PostgresDsn | None = None
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # --- Redis -------------------------------------------------------------
    REDIS_URL: RedisDsn = "redis://localhost:6379/0"  # type: ignore[assignment]
    REDIS_TOKEN_BLOCKLIST_PREFIX: str = "blocklist:"

    # --- Logging -----------------------------------------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_JSON: bool = False

    # --- Broker (Kite) ------------------------------------------------------
    KITE_API_KEY: str = ""
    KITE_API_SECRET: str = ""

    # Encryption at rest for broker tokens. MUST differ from SECRET_KEY: leaking
    # the JWT signing key must not also open the broker vault.
    ENCRYPTION_KEY: str = ""

    # --- Trading safety -----------------------------------------------------
    # Both default to the safe setting. Live trading requires a deliberate act;
    # a misconfiguration must never be able to spend real money.
    LIVE_TRADING_ENABLED: bool = False
    TRADING_HALTED: bool = False  # the kill switch
    PAPER_STARTING_CASH: float = 1_000_000.0

    # --- TradingView webhook -------------------------------------------------
    # TradingView cannot sign requests, so a shared secret rides in the JSON
    # body. Empty means the webhook endpoint is CLOSED.
    TRADINGVIEW_WEBHOOK_SECRET: str = ""

    # --- Bootstrap superuser ----------------------------------------------
    FIRST_SUPERUSER_EMAIL: str = "admin@aitraderpro.local"
    FIRST_SUPERUSER_PASSWORD: str = "ChangeMe123!"

    # --- Derived -----------------------------------------------------------
    @property
    def async_database_uri(self) -> str:
        if self.DATABASE_URL:
            return str(self.DATABASE_URL).replace("postgresql://", "postgresql+asyncpg://", 1)
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_uri(self) -> str:
        """Used by Alembic, which runs migrations synchronously."""
        return self.async_database_uri.replace("postgresql+asyncpg://", "postgresql://", 1)

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
