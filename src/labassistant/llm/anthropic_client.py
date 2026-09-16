"""LLMClient implementation backed by the Anthropic Messages API."""

import anthropic

from labassistant.config import Settings, get_settings
from labassistant.llm.base import LLMResponse, Message, ToolCall, ToolDefinition, Usage


class MissingAPIKeyError(RuntimeError):
    pass


class AnthropicClient:
    """Thin wrapper: sends one request and converts the reply to an LLMResponse.

    It deliberately does not run the tool loop. The diagnosis agent owns the loop
    so it can log each step and switch tools off for experiments.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.anthropic_api_key:
            raise MissingAPIKeyError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
            )
        self._client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        request: dict = {
            "model": self.settings.llm_model,
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
            "system": system,
            "messages": messages,
        }
        # Only send `tools` when there are some; this is also how the
        # "no run_tests tool" experiment condition is expressed.
        if tools:
            request["tools"] = tools

        response = self._client.messages.create(**request)
        return self._to_llm_response(response)

    @staticmethod
    def _to_llm_response(response: anthropic.types.Message) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))

        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            usage=Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                # These are None when prompt caching was not involved.
                cache_creation_input_tokens=response.usage.cache_creation_input_tokens or 0,
                cache_read_input_tokens=response.usage.cache_read_input_tokens or 0,
            ),
            content=[block.model_dump(exclude_none=True) for block in response.content],
        )
