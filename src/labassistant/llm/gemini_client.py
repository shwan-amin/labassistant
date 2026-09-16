"""LLMClient implementation backed by Google's Gemini API (google-genai SDK).

The rest of Lab Assistant speaks the Anthropic message format (see base.py), so
this adapter translates in both directions:

    Anthropic-style                         Gemini
    ---------------------------------------------------------------------
    system prompt                        -> config.system_instruction
    role "assistant"                     -> role "model"
    {"type": "text"}                     -> Part(text=...)
    {"type": "tool_use", id, name, input}-> Part(function_call=...)
    {"type": "tool_result", tool_use_id} -> Part(function_response=...)
    tool {name, description, input_schema} -> FunctionDeclaration

Two Gemini details need care:
* Gemini may not give function calls an id, but our loop matches tool results to
  calls by id. We make one up when needed and keep Gemini's own id separately.
* Thinking models attach an opaque "thought signature" to parts, and expect it
  back on the next request. We store it (base64) inside the content block so it
  survives the round trip through the agent loop unchanged.
"""

import base64
import json
import uuid
from typing import Any

from google import genai
from google.genai import types

from labassistant.config import Settings, get_settings
from labassistant.llm.base import (
    LLMResponse,
    Message,
    MissingAPIKeyError,
    ToolCall,
    ToolDefinition,
    Usage,
)

# Gemini finish reasons that mean "blocked", reported as "refusal" like Anthropic does.
BLOCKED_REASONS = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}


class GeminiClient:
    """Thin wrapper: sends one request and converts the reply to an LLMResponse.

    Like AnthropicClient, it does not run the tool loop; the diagnosis agent does.
    Automatic function calling is switched off so the SDK never runs tools itself.
    """

    def __init__(self, settings: Settings | None = None, client: Any = None) -> None:
        self.settings = settings or get_settings()
        if client is not None:
            self._client = client  # injected in tests
            return
        if not self.settings.gemini_api_key:
            raise MissingAPIKeyError(
                "GEMINI_API_KEY is not set. Add it to .env (see .env.example)."
            )
        self._client = genai.Client(api_key=self.settings.gemini_api_key)

    def complete(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens or self.settings.llm_max_tokens,
            # Only send tools when there are some ("no run_tests tool" experiment).
            tools=[to_gemini_tool(tools)] if tools else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._client.models.generate_content(
            model=self.settings.model_name,
            contents=to_gemini_contents(messages),
            config=config,
        )
        return from_gemini_response(response)


# --- Anthropic-style request -> Gemini ---


def to_gemini_tool(tools: list[ToolDefinition]) -> types.Tool:
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters_json_schema=tool.get("input_schema", {"type": "object"}),
            )
            for tool in tools
        ]
    )


def to_gemini_contents(messages: list[Message]) -> list[types.Content]:
    # Tool results only carry the call id, but Gemini wants the function name too,
    # so remember names as we pass the calls.
    names_by_id: dict[str, str] = {}
    contents = []
    for message in messages:
        role = "model" if message["role"] == "assistant" else "user"
        blocks = message["content"]
        if isinstance(blocks, str):
            blocks = [{"type": "text", "text": blocks}]
        parts = [_to_part(block, names_by_id) for block in blocks]
        contents.append(types.Content(role=role, parts=parts))
    return contents


def _to_part(block: dict[str, Any], names_by_id: dict[str, str]) -> types.Part:
    signature = _decode_signature(block.get("gemini_thought_signature"))
    kind = block["type"]
    if kind == "text":
        return types.Part(text=block["text"], thought_signature=signature)
    if kind == "tool_use":
        names_by_id[block["id"]] = block["name"]
        call = types.FunctionCall(
            id=block.get("gemini_id"), name=block["name"], args=block["input"]
        )
        return types.Part(function_call=call, thought_signature=signature)
    if kind == "tool_result":
        text = _tool_result_text(block.get("content", ""))
        payload = {"error": text} if block.get("is_error") else {"result": text}
        response = types.FunctionResponse(
            name=names_by_id.get(block["tool_use_id"], "unknown_tool"),
            response=payload,
        )
        return types.Part(function_response=response)
    raise ValueError(f"unsupported content block type for Gemini: {kind!r}")


def _tool_result_text(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", json.dumps(block)) for block in content)


# --- Gemini response -> LLMResponse ---


def from_gemini_response(response: types.GenerateContentResponse) -> LLMResponse:
    usage = _usage(response.usage_metadata)
    if not response.candidates:
        # The prompt itself was blocked, so there is no candidate at all.
        return LLMResponse(stop_reason="refusal", usage=usage)

    candidate = response.candidates[0]
    parts = (candidate.content.parts if candidate.content else None) or []
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    content: list[dict[str, Any]] = []

    for part in parts:
        if part.thought:
            continue  # thought summaries are not part of the answer
        signature = _encode_signature(part.thought_signature)
        if part.function_call is not None:
            call = part.function_call
            call_id = call.id or f"gemini_call_{uuid.uuid4().hex[:12]}"
            args = dict(call.args or {})
            tool_calls.append(ToolCall(id=call_id, name=call.name or "", input=args))
            block = {"type": "tool_use", "id": call_id, "name": call.name, "input": args}
            if call.id:
                block["gemini_id"] = call.id
        elif part.text is not None:
            text_parts.append(part.text)
            block = {"type": "text", "text": part.text}
        else:
            continue
        if signature:
            block["gemini_thought_signature"] = signature
        content.append(block)

    return LLMResponse(
        text="".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=_stop_reason(candidate.finish_reason, bool(tool_calls)),
        usage=usage,
        content=content,
    )


def _stop_reason(finish_reason: types.FinishReason | None, has_tool_calls: bool) -> str:
    """Map to the Anthropic-style names the agent loop already understands."""
    if has_tool_calls:
        return "tool_use"
    name = finish_reason.name if finish_reason is not None else "STOP"
    if name == "MAX_TOKENS":
        return "max_tokens"
    if name in BLOCKED_REASONS:
        return "refusal"
    return "end_turn"


def _usage(metadata: types.GenerateContentResponseUsageMetadata | None) -> Usage:
    if metadata is None:
        return Usage()
    prompt = metadata.prompt_token_count or 0
    cached = metadata.cached_content_token_count or 0
    return Usage(
        # Gemini's prompt count includes cached tokens; Anthropic's input_tokens does not.
        input_tokens=prompt - cached,
        cache_read_input_tokens=cached,
        # Thinking tokens are billed as output, so count them there.
        output_tokens=(metadata.candidates_token_count or 0) + (metadata.thoughts_token_count or 0),
    )


def _encode_signature(signature: bytes | None) -> str | None:
    return base64.b64encode(signature).decode("ascii") if signature else None


def _decode_signature(signature: str | None) -> bytes | None:
    return base64.b64decode(signature) if signature else None
