"""Application settings, loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from labassistant.context.models import ContextMode


class Settings(BaseSettings):
    """All runtime configuration in one place.

    Field names map to environment variables case-insensitively, so `llm_model`
    is read from `LLM_MODEL`.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Optional so that tests and offline work never need a key. The real
    # Anthropic client checks for it and fails with a clear message instead.
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"
    llm_max_tokens: int = 16000

    # Maximum tokens of project context (code, repo map, spec) sent per check.
    # The context builder fills this in priority order and records what it dropped.
    context_token_budget: int = 20000
    # selection_only | file | full (see labassistant.context.models.ContextMode).
    context_mode: ContextMode = ContextMode.FULL
    # Files larger than this, or projects beyond the total, are skipped and recorded.
    max_file_bytes: int = 200_000
    max_project_bytes: int = 2_000_000

    # Wall-clock limit for one sandboxed test run.
    runner_timeout_seconds: float = 10.0

    database_path: Path = Path("labassistant.db")
    knowledge_dir: Path = Path("knowledge")
    sample_labs_dir: Path = Path("sample_labs")
    materials_dir: Path = Path("materials")
    eval_results_dir: Path = Path("eval/results")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so the environment is read once per process."""
    return Settings()
