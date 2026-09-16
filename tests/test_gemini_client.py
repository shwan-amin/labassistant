"""Offline tests for the Gemini adapter: SDK objects are built locally, no network."""

import base64

import pytest
from google.genai import types

from labassistant.config import Settings
from labassistant.llm import FakeLLMClient, MissingAPIKeyError, create_llm_client
from labassistant.llm.anthropic_client import AnthropicClient
from labassistant.llm.gemini_client import (
    GeminiClient,
    from_gemini_response,
    to_gemini_contents,
    to_gemini_tool,
)


def gemini_response(parts: list[dict], finish_reason: str = "STOP", usage: dict | None = None):
    return types.GenerateContentResponse.model_validate(
        {
            "candidates": [
                {"content": {"role": "model", "parts": parts}, "finish_reason": finish_reason}
            ],
            "usage_metadata": usage
            or {"prompt_token_count": 100, "candidates_token_count": 20, "thoughts_token_count": 5},
        }
    )


class RecordingModels:
    """Stands in for `genai.Client().models`, recording the request."""

    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        return self.response


class FakeGenaiClient:
    def __init__(self, response):
        self.models = RecordingModels(response)


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


# --- responses ---


def test_text_response() -> None:
    result = from_gemini_response(gemini_response([{"text": "Hello"}, {"text": " there"}]))

    assert result.text == "Hello there"
    assert result.stop_reason == "end_turn"
    assert result.tool_calls == []
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 25  # thinking tokens count as output


def test_function_call_without_id_gets_one() -> None:
    result = from_gemini_response(
        gemini_response([{"function_call": {"name": "run_tests", "args": {"test_ids": ["a"]}}}])
    )

    assert result.stop_reason == "tool_use"
    [call] = result.tool_calls
    assert call.name == "run_tests" and call.input == {"test_ids": ["a"]}
    assert call.id.startswith("gemini_call_")
    assert result.content == [
        {"type": "tool_use", "id": call.id, "name": "run_tests", "input": {"test_ids": ["a"]}}
    ]


def test_thought_signature_survives_round_trip() -> None:
    signature = b"\x01opaque-signature\xff"
    result = from_gemini_response(
        gemini_response(
            [
                {
                    "function_call": {"id": "g1", "name": "run_tests", "args": {}},
                    "thought_signature": base64.b64encode(signature).decode(),
                }
            ]
        )
    )
    block = result.content[0]
    assert block["gemini_id"] == "g1"

    # The agent appends the content unchanged, then sends it back.
    contents = to_gemini_contents([{"role": "assistant", "content": result.content}])
    part = contents[0].parts[0]
    assert contents[0].role == "model"
    assert part.thought_signature == signature
    assert part.function_call.id == "g1"


def test_thought_summaries_are_skipped() -> None:
    result = from_gemini_response(
        gemini_response([{"text": "thinking...", "thought": True}, {"text": "answer"}])
    )
    assert result.text == "answer"


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [("MAX_TOKENS", "max_tokens"), ("SAFETY", "refusal"), ("OTHER", "end_turn")],
)
def test_finish_reasons(finish_reason: str, expected: str) -> None:
    result = from_gemini_response(gemini_response([{"text": "x"}], finish_reason=finish_reason))
    assert result.stop_reason == expected


def test_blocked_prompt_with_no_candidates() -> None:
    response = types.GenerateContentResponse.model_validate(
        {"candidates": [], "usage_metadata": {"prompt_token_count": 7}}
    )
    result = from_gemini_response(response)
    assert result.stop_reason == "refusal"
    assert result.usage.input_tokens == 7


def test_cached_tokens_split_out() -> None:
    usage = {
        "prompt_token_count": 1000,
        "cached_content_token_count": 800,
        "candidates_token_count": 10,
    }
    result = from_gemini_response(gemini_response([{"text": "x"}], usage=usage))

    assert result.usage.input_tokens == 200
    assert result.usage.cache_read_input_tokens == 800
    assert result.usage.total_input_tokens == 1000


# --- requests ---


def test_messages_translate_including_tool_results() -> None:
    messages = [
        {"role": "user", "content": "Check this code"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Running tests"},
                {"type": "tool_use", "id": "call_1", "name": "run_tests", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": '{"status": "passed"}'},
            ],
        },
    ]
    contents = to_gemini_contents(messages)

    assert [c.role for c in contents] == ["user", "model", "user"]
    assert contents[0].parts[0].text == "Check this code"
    response_part = contents[2].parts[0].function_response
    assert response_part.name == "run_tests"  # recovered from the earlier call
    assert response_part.response == {"result": '{"status": "passed"}'}


def test_error_tool_result() -> None:
    messages = [
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "c", "name": "t", "input": {}}],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c", "content": "bad", "is_error": True}
            ],
        },
    ]
    assert to_gemini_contents(messages)[1].parts[0].function_response.response == {"error": "bad"}


def test_tool_definitions_translate() -> None:
    tool = to_gemini_tool(
        [{"name": "run_tests", "description": "Run tests", "input_schema": {"type": "object"}}]
    )
    [declaration] = tool.function_declarations
    assert declaration.name == "run_tests"
    assert declaration.parameters_json_schema == {"type": "object"}


def test_complete_sends_config_and_model() -> None:
    fake = FakeGenaiClient(gemini_response([{"text": "ok"}]))
    client = GeminiClient(settings(llm_model="gemini-test"), client=fake)

    result = client.complete(
        system="be Socratic",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "run_tests", "description": "d", "input_schema": {"type": "object"}}],
        max_tokens=500,
    )

    kwargs = fake.models.kwargs
    assert result.text == "ok"
    assert kwargs["model"] == "gemini-test"
    assert kwargs["config"].system_instruction == "be Socratic"
    assert kwargs["config"].max_output_tokens == 500
    assert kwargs["config"].automatic_function_calling.disable is True
    assert kwargs["config"].tools[0].function_declarations[0].name == "run_tests"


def test_no_tools_sends_no_tools() -> None:
    fake = FakeGenaiClient(gemini_response([{"text": "ok"}]))
    GeminiClient(settings(), client=fake).complete(
        system="", messages=[{"role": "user", "content": "x"}]
    )
    assert fake.models.kwargs["config"].tools is None


# --- factory and keys ---


def test_missing_gemini_key() -> None:
    with pytest.raises(MissingAPIKeyError, match="GEMINI_API_KEY"):
        GeminiClient(settings(gemini_api_key=None))


def test_factory_picks_provider() -> None:
    assert isinstance(
        create_llm_client(settings(llm_provider="gemini", gemini_api_key="k")), GeminiClient
    )
    assert isinstance(
        create_llm_client(settings(llm_provider="anthropic", anthropic_api_key="k")),
        AnthropicClient,
    )


def test_fake_client_still_satisfies_interface() -> None:
    assert FakeLLMClient([]).calls == []
