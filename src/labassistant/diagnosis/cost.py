"""Estimated cost of a check, from token usage and a per-model price table.

Prices are USD per million tokens. Only models with prices we have verified are
listed; anything else returns None rather than a made-up number. Extra prices can
be supplied through settings (e.g. for a paid Gemini tier) without code changes.
"""

from pydantic import BaseModel

from labassistant.llm.base import Usage


class ModelPrice(BaseModel):
    input: float
    output: float
    cache_read: float
    cache_write: float


# Anthropic list prices (cache read 0.1x input, 5-minute cache write 1.25x input).
KNOWN_PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-5": ModelPrice(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5),
    "claude-opus-5": ModelPrice(input=5.0, output=25.0, cache_read=0.5, cache_write=6.25),
    "claude-haiku-4-5": ModelPrice(input=1.0, output=5.0, cache_read=0.1, cache_write=1.25),
}


def estimate_cost_usd(
    model: str, usage: Usage, extra_prices: dict[str, ModelPrice] | None = None
) -> float | None:
    price = {**KNOWN_PRICES, **(extra_prices or {})}.get(model)
    if price is None:
        return None
    per_token = 1 / 1_000_000
    total = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_input_tokens * price.cache_read
        + usage.cache_creation_input_tokens * price.cache_write
    ) * per_token
    return round(total, 6)
