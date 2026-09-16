"""A scripted, offline LLM client for tests."""

from dataclasses import dataclass
from typing import Any

from conceptcoach.llm.base import LLMResponse, Message, ToolCall, ToolDefinition


@dataclass
class RecordedCall:
    """What the code under test sent to the model, for assertions."""

    system: str
    messages: list[Message]
    tools: list[ToolDefinition] | None
    max_tokens: int | None


class FakeLLMClient:
    """Returns pre-scripted responses in order and records every call.

    Example:
        fake = FakeLLMClient([FakeLLMClient.tool_use("run_tests", {}), FakeLLMClient.text("{}")])
    """

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[RecordedCall] = []

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        # Copy the messages: the caller usually keeps appending to the same list,
        # and we want a snapshot of what was sent at this point.
        self.calls.append(RecordedCall(system, [dict(m) for m in messages], tools, max_tokens))
        if not self._responses:
            raise AssertionError("FakeLLMClient ran out of scripted responses")
        return self._responses.pop(0)

    @staticmethod
    def text(text: str) -> LLMResponse:
        """Build a plain text response that ends the turn."""
        return LLMResponse(
            text=text,
            stop_reason="end_turn",
            content=[{"type": "text", "text": text}],
        )

    @staticmethod
    def tool_use(
        name: str, tool_input: dict[str, Any], call_id: str = "toolu_fake_1"
    ) -> LLMResponse:
        """Build a response in which the model asks to call one tool."""
        call = ToolCall(id=call_id, name=name, input=tool_input)
        return LLMResponse(
            tool_calls=[call],
            stop_reason="tool_use",
            content=[{"type": "tool_use", "id": call_id, "name": name, "input": tool_input}],
        )
