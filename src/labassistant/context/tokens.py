"""Token counting for the context budget."""

import math
from typing import Protocol


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class EstimatingTokenCounter:
    """Offline estimate: about 4 characters per token for English and code.

    Budgeting happens on every check and in tests, so it must be fast and need no
    network. Anthropic's count_tokens endpoint gives exact numbers, and real usage
    is recorded from API responses, so the evaluation can check how far off this is.
    """

    def __init__(self, chars_per_token: float = 4.0) -> None:
        self.chars_per_token = chars_per_token

    def count(self, text: str) -> int:
        return math.ceil(len(text) / self.chars_per_token) if text else 0
