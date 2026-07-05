"""Token-cost estimation (provider-neutral data, no SDK).

A small list-price table keyed by model family. Used to stamp `cost_usd` on each run at write
time (you can't reliably backfill spend later). Prices are approximate USD per 1M tokens — update
them here as pricing changes; nothing else needs to change.
"""

from __future__ import annotations

# (input_per_million, output_per_million) USD. Longest prefix match wins.
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4": (5.0, 25.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4": (1.0, 5.0),
    "claude-fable-5": (6.0, 30.0),
}


def price_for(model: str | None) -> tuple[float, float] | None:
    """Return (input, output) per-million pricing for a model, or None if unknown."""
    if not model:
        return None
    matches = [(k, v) for k, v in _PRICING.items() if model.startswith(k)]
    if not matches:
        return None
    # Longest key = most specific family match.
    return max(matches, key=lambda kv: len(kv[0]))[1]


def estimate_cost(
    model: str | None, prompt_tokens: int | None, completion_tokens: int | None
) -> float | None:
    """USD estimate for one run. Returns None (not a wrong guess) when model or tokens are unknown."""
    price = price_for(model)
    if price is None or prompt_tokens is None or completion_tokens is None:
        return None
    in_rate, out_rate = price
    return round(prompt_tokens / 1_000_000 * in_rate + completion_tokens / 1_000_000 * out_rate, 6)
