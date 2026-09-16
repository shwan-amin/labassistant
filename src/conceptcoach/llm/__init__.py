"""LLM client interface and implementations.

Everything else in ConceptCoach depends on `LLMClient`, never on the Anthropic SDK
directly. That lets tests and evaluation swap in `FakeLLMClient`.
"""

from conceptcoach.llm.base import LLMClient, LLMResponse, ToolCall, Usage
from conceptcoach.llm.fake import FakeLLMClient

__all__ = ["FakeLLMClient", "LLMClient", "LLMResponse", "ToolCall", "Usage"]
