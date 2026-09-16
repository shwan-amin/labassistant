import pytest
from pydantic import BaseModel

from labassistant.llm import FakeLLMClient
from labassistant.llm.structured import StructuredOutputError, complete_json


class Answer(BaseModel):
    value: int


def test_valid_first_time() -> None:
    fake = FakeLLMClient([FakeLLMClient.text('{"value": 3}')])
    result, usage = complete_json(fake, system="s", user="u", model=Answer)
    assert result.value == 3
    assert usage.output_tokens > 0


def test_retries_once_with_error_then_succeeds() -> None:
    fake = FakeLLMClient(
        [FakeLLMClient.text('{"value": "three"}'), FakeLLMClient.text('{"value": 3}')]
    )
    result, _ = complete_json(fake, system="s", user="u", model=Answer)

    assert result.value == 3
    retry_message = fake.calls[1].messages[-1]["content"]
    assert "could not be used" in retry_message and "value" in retry_message


def test_invalid_twice_fails() -> None:
    fake = FakeLLMClient([FakeLLMClient.text("nope"), FakeLLMClient.text("still nope")])
    with pytest.raises(StructuredOutputError, match="invalid twice"):
        complete_json(fake, system="s", user="u", model=Answer)


def test_refusal_fails() -> None:
    refusal = FakeLLMClient.text("")
    refusal.stop_reason = "refusal"
    with pytest.raises(StructuredOutputError, match="declined"):
        complete_json(FakeLLMClient([refusal]), system="s", user="u", model=Answer)
