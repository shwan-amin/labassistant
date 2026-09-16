from pathlib import Path

import pytest

from labassistant.config import Settings


def test_defaults_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_MODEL", "LLM_PROVIDER", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)  # ignore any local .env
    assert settings.llm_provider == "gemini"
    assert settings.model_name == "gemini-3.6-flash"
    assert settings.anthropic_api_key is None
    assert settings.gemini_api_key is None


def test_reads_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "some-other-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_PATH", "/tmp/cc.db")
    settings = Settings(_env_file=None)
    assert settings.model_name == "some-other-model"
    assert settings.anthropic_api_key == "test-key"
    assert settings.database_path == Path("/tmp/cc.db")


def test_context_token_budget_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXT_TOKEN_BUDGET", "5000")
    assert Settings(_env_file=None).context_token_budget == 5000
    monkeypatch.delenv("CONTEXT_TOKEN_BUDGET")
    assert Settings(_env_file=None).context_token_budget == 20000


def test_model_default_follows_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert Settings(_env_file=None).model_name == "claude-sonnet-5"
    monkeypatch.setenv("LLM_MODEL", "")  # blank in .env means "use the default"
    assert Settings(_env_file=None).model_name == "claude-sonnet-5"
