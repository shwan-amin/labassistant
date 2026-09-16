import pytest

from conceptcoach.config import Settings
from conceptcoach.llm import FakeLLMClient, LLMClient
from conceptcoach.llm.anthropic_client import AnthropicClient, MissingAPIKeyError


def test_fake_client_returns_scripted_responses_in_order() -> None:
    fake = FakeLLMClient(
        [FakeLLMClient.tool_use("run_tests", {"code": "x"}), FakeLLMClient.text("done")]
    )

    first = fake.complete(system="sys", messages=[{"role": "user", "content": "hi"}])
    second = fake.complete(system="sys", messages=[])

    assert first.stop_reason == "tool_use"
    assert first.tool_calls[0].name == "run_tests"
    assert first.tool_calls[0].input == {"code": "x"}
    assert second.text == "done"
    assert second.stop_reason == "end_turn"


def test_fake_client_records_calls() -> None:
    fake = FakeLLMClient([FakeLLMClient.text("ok")])
    tools = [{"name": "run_tests", "input_schema": {"type": "object"}}]

    fake.complete(system="be kind", messages=[{"role": "user", "content": "q"}], tools=tools)

    assert len(fake.calls) == 1
    assert fake.calls[0].system == "be kind"
    assert fake.calls[0].tools == tools


def test_fake_client_fails_loudly_when_script_runs_out() -> None:
    fake = FakeLLMClient([])
    with pytest.raises(AssertionError, match="ran out"):
        fake.complete(system="", messages=[])


def test_fake_client_satisfies_interface() -> None:
    client: LLMClient = FakeLLMClient([])  # type checkers verify this assignment
    assert hasattr(client, "complete")


def test_anthropic_client_requires_api_key() -> None:
    with pytest.raises(MissingAPIKeyError):
        AnthropicClient(Settings(_env_file=None, anthropic_api_key=None))


def test_anthropic_response_conversion_without_network() -> None:
    from anthropic.types import Message

    raw = Message.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-5",
            "stop_reason": "tool_use",
            "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 7},
            "content": [
                {"type": "text", "text": "Let me run the tests."},
                {"type": "tool_use", "id": "toolu_1", "name": "run_tests", "input": {"a": 1}},
            ],
        }
    )

    result = AnthropicClient._to_llm_response(raw)

    assert result.text == "Let me run the tests."
    assert result.tool_calls[0].id == "toolu_1"
    assert result.tool_calls[0].input == {"a": 1}
    assert result.usage.input_tokens == 12
    assert result.content[1]["type"] == "tool_use"
