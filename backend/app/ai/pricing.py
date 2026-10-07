"""Cost estimates from token usage (for spending caps; not a bill)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DEFAULT_FILE = Path(__file__).with_name("pricing.toml")


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_write: float
    cache_read: float


@cache
def load_prices(path: Path = DEFAULT_FILE) -> dict[str, Price]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {name: Price(**values) for name, values in data.get("models", {}).items()}


def price_for(model: str, prices: dict[str, Price]) -> Price:
    if model in prices:
        return prices[model]
    # Unknown model: assume the most expensive known one so caps stay conservative.
    return max(prices.values(), key=lambda p: p.output)


def cost_usd(model: str, prices: dict[str, Price], *, input_tokens: int, output_tokens: int,
             cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    p = price_for(model, prices)
    total = (
        input_tokens * p.input
        + output_tokens * p.output
        + cache_read_tokens * p.cache_read
        + cache_write_tokens * p.cache_write
    )
    return round(total / 1_000_000, 6)
