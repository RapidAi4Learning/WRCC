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

    # ── Scraper (politeness + bounded retries) ──
    scraper_base_url: str = "https://wrcc.nsw.edu.au"
    scraper_request_delay_ms: int = 500
    scraper_max_retries: int = 3
    scraper_timeout_seconds: float = 20.0
    scraper_user_agent: str = "WRCC-SocialMediaMarketing/1.0 (+https://wrcc.nsw.edu.au)"

    # ── Reference URL enrichment (best-effort, never blocks generation) ──
    reference_fetch_timeout_seconds: float = 8.0
    reference_fetch_max_chars: int = 4000

    # ── Publishing (mock-first, D8 — see docs/PUBLISH-PLAN.md) ──
    publish_mock: bool = True
    # Public HTTPS origin of *this* backend. Builds the OAuth redirect URIs and
    # the image URLs Meta fetches server-side, so it cannot be inferred from a
    # request (which may arrive via a proxy or an internal hostname).
    public_api_base_url: str = ""
    # Where the networks fetch post images from. Defaults to
    # `public_api_base_url`; set separately only when the two genuinely differ.
    #
    # They differ whenever the public host is a throwaway tunnel. An OAuth
    # redirect URI has to match a value registered in a provider dashboard, so
    # it wants a stable host; an image URL is just downloaded and is registered
    # nowhere, so an ephemeral host costs nothing. Tying both to one setting
    # forces a dashboard edit every time the tunnel restarts.
    public_media_base_url: str = ""

    @property
    def media_base_url(self) -> str:
        return self.public_media_base_url or self.public_api_base_url

    # Fernet key for tokens at rest:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = ""
    # Signs public image URLs. Deliberately separate from auth_secret: leaking
    # the one that signs images must not let anyone forge a session.
    media_signing_secret: str = ""
    media_url_ttl_seconds: int = 900
    publish_timeout_seconds: float = 30.0
    publish_max_attempts: int = 3
    # Exponential backoff base between retries of a throttled/transient call.
    # Tests set this to 0 so the suite does not actually sleep.
    publish_retry_base_delay_seconds: float = 0.5
    # Instagram builds the post in a container before it can be published;
    # images are usually immediate, but the API is asynchronous by contract.
    instagram_container_poll_attempts: int = 12
    instagram_container_poll_delay_seconds: float = 2.0
    # An attempt still `pending` after this long is reported as unknown rather
    # than retried — we may have posted and lost the response.
    publish_pending_stale_seconds: int = 300

    # ── Meta (Facebook + Instagram) ──
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_graph_version: str = "v23.0"
    # Set when using a Facebook Login for Business configuration; the dialog
    # then derives permissions from the dashboard and `scope` must be omitted
    # (business-type apps reject bare scopes as "Invalid Scopes").
    meta_login_config_id: str = ""

    # ── LinkedIn ──
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    linkedin_api_version: str = "202506"
    # urn:li:organization:{id} — or urn:li:person:{id} for the member fallback.
    linkedin_author_urn: str = ""

    @property
    def graph_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.meta_graph_version}"

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

        if not self.publish_mock:
            required = {
                "PUBLIC_API_BASE_URL": self.public_api_base_url,
                "TOKEN_ENCRYPTION_KEY": self.token_encryption_key,
                "MEDIA_SIGNING_SECRET": self.media_signing_secret,
                "META_APP_ID": self.meta_app_id,
                "META_APP_SECRET": self.meta_app_secret,
                "LINKEDIN_CLIENT_ID": self.linkedin_client_id,
                "LINKEDIN_CLIENT_SECRET": self.linkedin_client_secret,
            }
            missing.extend(
                f"{name} (required when PUBLISH_MOCK=false)"
                for name, value in required.items()
                if not value
            )
            # Both of these must differ from AUTH_SECRET. Reuse is easy to fall
            # into — every one of them is "a long random string" — and it fuses
            # three separate blast radii into one: a single leak would forge
            # sessions, decrypt every stored OAuth token, and sign image URLs.
            for name, value in (
                ("MEDIA_SIGNING_SECRET", self.media_signing_secret),
                ("TOKEN_ENCRYPTION_KEY", self.token_encryption_key),
            ):
                if value and value == self.auth_secret:
                    missing.append(
                        f"{name} (must differ from AUTH_SECRET — one leaked key "
                        "must not also be able to forge sessions)"
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
