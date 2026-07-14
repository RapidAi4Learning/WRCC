"""Application configuration.

Loads and validates every environment variable. Fails fast at startup when a
required secret is missing while the corresponding mock flag is disabled
(validate at system boundaries — never trust external data).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "staging", "production"]

_AUTH_SECRET_PLACEHOLDER = "change-me-32-bytes-min"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Core ──
    app_env: AppEnv = "local"
    app_port: int = 8000
    log_level: str = "INFO"
    frontend_origin: str = "http://localhost:3000"

    # ── Database ──
    database_url: str = "postgresql+asyncpg://wrcc:wrcc@localhost:5432/wrcc"
    db_pool_size: int = 10

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalize_async_driver(cls, value: str) -> str:
        """Coerce a plain Postgres URL to the asyncpg driver SQLAlchemy needs.

        Managed providers inject ``DATABASE_URL`` as ``postgresql://`` or legacy
        ``postgres://``; asyncpg also rejects the libpq ``sslmode`` query param,
        so both are normalized here.
        """
        if value.startswith("postgres://"):
            value = "postgresql+asyncpg://" + value[len("postgres://") :]
        elif value.startswith("postgresql://"):
            value = "postgresql+asyncpg://" + value[len("postgresql://") :]

        if "sslmode=" in value:
            from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

            parts = urlsplit(value)
            query = [(k, v) for k, v in parse_qsl(parts.query) if k != "sslmode"]
            value = urlunsplit(parts._replace(query=urlencode(query)))
        return value

    # ── Auth (§4a: argon2 + JWT in an httpOnly cookie) ──
    auth_secret: str = _AUTH_SECRET_PLACEHOLDER
    jwt_expires_minutes: int = 480
    jwt_issuer: str = "wrcc"
    jwt_audience: str = "wrcc-app"
    session_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    session_cookie_domain: str | None = None
    # Seeded admin credentials (no self-service registration). The seed script
    # fails when these are missing — never hardcoded defaults.
    admin_email: str = ""
    admin_password: str = ""

    # ── Login rate limiting ──
    login_rate_limit_max: int = 5
    login_rate_limit_window_seconds: int = 60

    # ── LLM (mock-first, D3) ──
    llm_mock: bool = True
    llm_provider: Literal["gemini", "openai"] = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"

    @property
    def live_model_name(self) -> str:
        """Model recorded in ai_metadata when LLM_MOCK=false."""
        if self.llm_provider == "openai":
            return self.openai_model
        return self.gemini_model

    # ── Images (mock-first: follows LLM_MOCK; live requires LLM_PROVIDER=openai) ──
    image_model: str = "gpt-image-1"
    image_size: str = "1024x1024"
    image_quality: Literal["low", "medium", "high", "auto"] = "medium"
    media_dir: str = "media"

    # ── Scraper (politeness + bounded retries) ──
    scraper_base_url: str = "https://wrcc.nsw.edu.au"
    scraper_request_delay_ms: int = 500
    scraper_max_retries: int = 3
    scraper_timeout_seconds: float = 20.0
    scraper_user_agent: str = "WRCC-ContentStudio/1.0 (+https://wrcc.nsw.edu.au)"

    # ── Reference URL enrichment (best-effort, never blocks generation) ──
    reference_fetch_timeout_seconds: float = 8.0
    reference_fetch_max_chars: int = 4000

    @model_validator(mode="after")
    def _validate_required_when_live(self) -> Settings:
        """Enforce that live mode supplies the secrets it needs."""
        missing: list[str] = []

        if not self.llm_mock:
            if self.llm_provider == "gemini" and not self.gemini_api_key:
                missing.append(
                    "GEMINI_API_KEY (required when LLM_MOCK=false and LLM_PROVIDER=gemini)"
                )
            if self.llm_provider == "openai" and not self.openai_api_key:
                missing.append(
                    "OPENAI_API_KEY (required when LLM_MOCK=false and LLM_PROVIDER=openai)"
                )

        if self.app_env == "production":
            if self.auth_secret == _AUTH_SECRET_PLACEHOLDER:
                missing.append("AUTH_SECRET (placeholder not allowed in production)")
            if len(self.auth_secret) < 32:
                missing.append("AUTH_SECRET (must be at least 32 bytes in production)")

        if missing:
            raise ValueError(
                "Invalid configuration. Missing/placeholder values:\n  - "
                + "\n  - ".join(missing)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
