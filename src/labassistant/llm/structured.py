"""Getting validated JSON out of an LLM.

Shared by the diagnosis agent, question generation and answer evaluation:
ask for a JSON object, validate it with a Pydantic model, and on failure retry
once with the validation error before failing clearly.
"""

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from labassistant.llm.base import LLMClient, Message, Usage

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

RETRY_TEMPLATE = """\
Your previous reply could not be used: {error}
Reply again with only the corrected JSON object, following the required shape."""


class InvalidOutputError(ValueError):
    """The model's reply is not usable JSON of the right shape."""


class StructuredOutputError(RuntimeError):
    """The model gave invalid output twice, or refused."""


def parse_json_model(text: str, model: type[T]) -> T:
    """Parse the reply, tolerating a ```json fence or text around the object."""
    candidate = text.strip()
    if match := _FENCE.match(candidate):
        candidate = match.group(1)
    elif not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            raise InvalidOutputError("no JSON object found in the reply")
        candidate = candidate[start : end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise InvalidOutputError(f"invalid JSON: {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise InvalidOutputError(f"JSON does not match the required shape: {exc}") from exc


def complete_json(
    client: LLMClient,
    *,
    system: str,
    user: str,
    model: type[T],
    max_tokens: int = 4_000,
) -> tuple[T, Usage]:
    """One JSON answer with no tools. Returns (parsed model, total usage)."""
    messages: list[Message] = [{"role": "user", "content": user}]
    usage = Usage()
    for attempt in range(2):
        response = client.complete(system=system, messages=messages, max_tokens=max_tokens)
        usage = usage + response.usage
        if response.stop_reason == "refusal":
            raise StructuredOutputError("the model declined to answer")
        try:
            return parse_json_model(response.text, model), usage
        except InvalidOutputError as exc:
            if attempt == 1:
                message = f"model output was invalid twice; last error: {exc}"
                raise StructuredOutputError(message) from exc
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": RETRY_TEMPLATE.format(error=exc)})
    raise AssertionError("unreachable")
