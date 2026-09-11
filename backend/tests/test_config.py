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


def test_live_llm_requires_openai_key_for_openai_provider() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        make_settings(llm_mock=False, llm_provider="openai", openai_api_key="")
    settings = make_settings(
        llm_mock=False, llm_provider="openai", openai_api_key="real-key"
    )
    assert settings.openai_api_key == "real-key"
    # The gemini key is not required when the openai provider is selected.
    assert settings.gemini_api_key == ""


def test_llm_provider_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        make_settings(llm_provider="mistral")


def test_live_model_name_follows_provider() -> None:
    assert make_settings().live_model_name == make_settings().gemini_model
    settings = make_settings(llm_provider="openai", openai_model="gpt-5-mini")
    assert settings.live_model_name == "gpt-5-mini"


def test_latency_limits_have_safe_defaults() -> None:
    # docs/GENERATION-LATENCY-PLAN.md: a whole generation must finish well
    # inside the ~120 s after which the host kills the request with a 502.
    settings = make_settings()
    assert settings.openai_reasoning_effort == "low"
    assert settings.llm_timeout_seconds == 40
    assert settings.llm_max_attempts == 2
    assert settings.llm_max_concurrency == 9
    assert settings.generation_deadline_seconds == 95
    assert settings.image_timeout_seconds == 100


@pytest.mark.parametrize("effort", ["", "minimal", "low", "medium", "high"])
def test_reasoning_effort_accepts_blank_and_known_levels(effort: str) -> None:
    assert make_settings(openai_reasoning_effort=effort).openai_reasoning_effort == effort


def test_reasoning_effort_rejects_unknown_level() -> None:
    with pytest.raises(ValueError):
        make_settings(openai_reasoning_effort="turbo")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_timeout_seconds", 0),
        ("llm_max_attempts", 0),
        ("llm_max_attempts", 4),
        ("llm_max_concurrency", 0),
        ("llm_max_concurrency", 21),
        ("generation_deadline_seconds", 0),
        ("image_timeout_seconds", 0),
    ],
)
def test_latency_limits_reject_out_of_range(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        make_settings(**{field: value})


@pytest.mark.parametrize("field", ["generation_deadline_seconds", "image_timeout_seconds"])
def test_request_deadlines_stay_under_the_proxy_limit(field: str) -> None:
    # 115 s leaves a margin under LiteSpeed's ~120 s: we must answer first.
    with pytest.raises(ValueError, match="115"):
        make_settings(**{field: 115})


def test_production_rejects_placeholder_auth_secret() -> None:
    with pytest.raises(ValueError, match="AUTH_SECRET"):
        make_settings(app_env="production", auth_secret="change-me-32-bytes-min")
    with pytest.raises(ValueError, match="at least 32 bytes"):
        make_settings(app_env="production", auth_secret="short")
