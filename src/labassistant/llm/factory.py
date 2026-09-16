"""Create the configured LLM client."""

from labassistant.config import LLMProvider, Settings, get_settings
from labassistant.llm.base import LLMClient


def create_llm_client(settings: Settings | None = None) -> LLMClient:
    settings = settings or get_settings()
    # Imported lazily so code (and tests) that never make real calls don't need
    # either SDK to initialise.
    if settings.llm_provider == LLMProvider.GEMINI:
        from labassistant.llm.gemini_client import GeminiClient

        return GeminiClient(settings)
    from labassistant.llm.anthropic_client import AnthropicClient

    return AnthropicClient(settings)
