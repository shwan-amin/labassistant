"""Application settings, loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    database_path: Path = Path("conceptcoach.db")
    knowledge_dir: Path = Path("knowledge")
    tasks_dir: Path = Path("tasks")
    materials_dir: Path = Path("materials")
    eval_results_dir: Path = Path("eval/results")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so the environment is read once per process."""
    return Settings()
