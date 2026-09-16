"""A scripted, offline LLM client for tests."""

import json
from dataclasses import dataclass
from typing import Any

from labassistant.llm.base import LLMResponse, Message, ToolCall, ToolDefinition, Usage

# Rough rule of thumb for English text and code. Good enough for fake numbers;
# never used for real budgeting.
CHARS_PER_TOKEN = 4


@dataclass
class RecordedCall:
    """What the code under test sent to the model, for assertions."""

    system: str
    messages: list[Message]
    tools: list[ToolDefinition] | None
    max_tokens: int | None


class FakeLLMClient:
    """Returns pre-scripted responses in order and records every call.

    If a scripted response has no usage set, the fake fills in an estimate from
    the size of the request and response, so cost-tracking code has real-looking
    numbers to work with in tests.

    Example:
        fake = FakeLLMClient([FakeLLMClient.tool_use("run_tests", {}), FakeLLMClient.text("{}")])
    """

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[RecordedCall] = []
        self.responses_returned: list[LLMResponse] = []

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
        response = self._responses.pop(0)
        if response.usage == Usage():
            response = response.model_copy(
                update={"usage": _estimate_usage(system, messages, tools, response)}
            )
        self.responses_returned.append(response)
        return response

    @property
    def total_usage(self) -> Usage:
        return sum((r.usage for r in self.responses_returned), Usage())

    @staticmethod
    def text(text: str, usage: Usage | None = None) -> LLMResponse:
        """Build a plain text response that ends the turn."""
        return LLMResponse(
            text=text,
            stop_reason="end_turn",
            usage=usage or Usage(),
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


def _estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return max(1, len(text) // CHARS_PER_TOKEN)


def _estimate_usage(
    system: str,
    messages: list[Message],
    tools: list[ToolDefinition] | None,
    response: LLMResponse,
) -> Usage:
    return Usage(
        input_tokens=_estimate_tokens(system)
        + _estimate_tokens(messages)
        + _estimate_tokens(tools or []),
        output_tokens=_estimate_tokens(response.content),
    )
