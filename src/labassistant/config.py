"""Application settings, loaded from environment variables (and an optional .env file)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from labassistant.context.models import ContextMode


class LLMProvider(StrEnum):
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"


DEFAULT_MODELS = {
    LLMProvider.GEMINI: "gemini-3.6-flash",
    LLMProvider.ANTHROPIC: "claude-sonnet-5",
}


class Settings(BaseSettings):
    """All runtime configuration in one place.

    Field names map to environment variables case-insensitively, so `llm_model`
    is read from `LLM_MODEL`.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Which LLM service to call: "gemini" or "anthropic".
    llm_provider: LLMProvider = LLMProvider.GEMINI
    # Keys are optional so tests and offline work never need one. The real
    # clients check for their key and fail with a clear message instead.
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    # Leave unset to use the provider's default model (see DEFAULT_MODELS).
    llm_model: str | None = None
    llm_max_tokens: int = 16000

    # Maximum tokens of project context (code, repo map, spec) sent per check.
    # The context builder fills this in priority order and records what it dropped.
    context_token_budget: int = 20000
    # selection_only | file | full (see labassistant.context.models.ContextMode).
    context_mode: ContextMode = ContextMode.FULL
    # Files larger than this, or projects beyond the total, are skipped and recorded.
    max_file_bytes: int = 200_000
    max_project_bytes: int = 2_000_000

    # Show feedback directly instead of asking Socratic questions first.
    skip_questioning: bool = False
    # Identifies the learner in the local learner model (no accounts in this prototype).
    student_id: str = "local-student"

    # Wall-clock limit for one sandboxed test run.
    runner_timeout_seconds: float = 10.0

    database_path: Path = Path("labassistant.db")
    knowledge_dir: Path = Path("knowledge")
    sample_labs_dir: Path = Path("sample_labs")
    materials_dir: Path = Path("materials")
    # Local only (gitignored): transcripts, slide text and thumbnails.
    processed_materials_dir: Path = Path("data/raw/processed")
    eval_results_dir: Path = Path("eval/results")

    @property
    def model_name(self) -> str:
        return self.llm_model or DEFAULT_MODELS[self.llm_provider]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so the environment is read once per process."""
    return Settings()
