"""LLM client interface and implementations.

Everything else in Lab Assistant depends on `LLMClient`, never on a provider SDK
directly. That lets the provider be switched with LLM_PROVIDER, and lets tests
and evaluation swap in `FakeLLMClient`.
"""

from labassistant.llm.base import LLMClient, LLMResponse, MissingAPIKeyError, ToolCall, Usage
from labassistant.llm.factory import create_llm_client
from labassistant.llm.fake import FakeLLMClient

__all__ = [
    "FakeLLMClient",
    "LLMClient",
    "LLMResponse",
    "MissingAPIKeyError",
    "ToolCall",
    "Usage",
    "create_llm_client",
]
