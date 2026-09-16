"""The small interface every LLM client implements."""

from typing import Any, Protocol

from pydantic import BaseModel, Field

# Messages and tool definitions use the Anthropic Messages API shape
# (plain dicts like {"role": "user", "content": ...}). Every provider we care
# about can map onto it, and it avoids inventing a parallel format.
Message = dict[str, Any]
ToolDefinition = dict[str, Any]


class ToolCall(BaseModel):
    """A request from the model to run one of our tools."""

    id: str
    name: str
    input: dict[str, Any]


class Usage(BaseModel):
    """Token counts for one call, or a running total across calls.

    Anthropic reports cached prompt tokens separately from `input_tokens`:
    cache writes cost a little more than normal input, cache reads much less.
    Keeping all three lets the evaluation estimate real cost per check.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + other.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
        )


class LLMResponse(BaseModel):
    """A provider-neutral view of one model response."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    # e.g. "end_turn", "tool_use", "max_tokens", "refusal"
    stop_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    # The raw content blocks, as dicts. The agent loop appends these to the
    # conversation unchanged so tool_use ids line up with our tool_result blocks.
    content: list[dict[str, Any]] = Field(default_factory=list)


class LLMClient(Protocol):
    """Anything with this `complete` method can drive Lab Assistant.

    A Protocol (structural typing) means implementations don't need to inherit
    from anything; they just need the right method signature.
    """

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...
