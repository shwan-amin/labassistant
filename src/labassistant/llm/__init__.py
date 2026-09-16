"""LLM client interface and implementations.

Everything else in Lab Assistant depends on `LLMClient`, never on the Anthropic SDK
directly. That lets tests and evaluation swap in `FakeLLMClient`.
"""

from labassistant.llm.base import LLMClient, LLMResponse, ToolCall, Usage
from labassistant.llm.fake import FakeLLMClient

__all__ = ["FakeLLMClient", "LLMClient", "LLMResponse", "ToolCall", "Usage"]
