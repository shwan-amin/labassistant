from pathlib import Path

import pytest

from labassistant.config import Settings


def test_defaults_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(_env_file=None)  # ignore any local .env
    assert settings.llm_model == "claude-sonnet-5"
    assert settings.anthropic_api_key is None


def test_reads_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "some-other-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_PATH", "/tmp/cc.db")
    settings = Settings(_env_file=None)
    assert settings.llm_model == "some-other-model"
    assert settings.anthropic_api_key == "test-key"
    assert settings.database_path == Path("/tmp/cc.db")
