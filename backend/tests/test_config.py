"""Settings validation and DATABASE_URL normalization."""

from __future__ import annotations

import pytest

from tests.conftest import make_settings


def test_defaults_boot_fully_mocked() -> None:
    settings = make_settings()
    assert settings.llm_mock is True
    assert settings.app_env == "local"


@pytest.mark.parametrize(
    "raw",
    [
        "postgres://u:p@host:5432/db",
        "postgresql://u:p@host:5432/db",
    ],
)
def test_database_url_is_coerced_to_asyncpg(raw: str) -> None:
    settings = make_settings(database_url=raw)
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_database_url_drops_sslmode_param() -> None:
    settings = make_settings(
        database_url="postgresql://u:p@host:5432/db?sslmode=require&application_name=x"
    )
    assert "sslmode" not in settings.database_url
    assert "application_name=x" in settings.database_url


def test_live_llm_requires_gemini_key() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        make_settings(llm_mock=False, gemini_api_key="")
    settings = make_settings(llm_mock=False, gemini_api_key="real-key")
    assert settings.gemini_api_key == "real-key"


def test_production_rejects_placeholder_auth_secret() -> None:
    with pytest.raises(ValueError, match="AUTH_SECRET"):
        make_settings(app_env="production", auth_secret="change-me-32-bytes-min")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        make_settings(app_env="production", auth_secret="short")
