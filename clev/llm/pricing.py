"""Per-model token prices, USD per 1M tokens (input, output). Update when providers change them.

Sources: OpenAI pricing docs (2026-09-24). Models not listed cost 0 in traces, with a warning.
"""

from __future__ import annotations

import logging

PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6-sol": (2.00, 10.00),
    "gpt-6-astra": (10.00, 50.00),
}

log = logging.getLogger(__name__)
_warned: set[str] = set()


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price = PRICES_PER_MILLION.get(model)
    if price is None:
        if model not in _warned:
            _warned.add(model)
            log.warning("No price for model %r; its cost is recorded as 0", model)
        return 0.0
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000
