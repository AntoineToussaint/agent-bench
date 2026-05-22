"""Per-model token pricing.

Prices live in `data/pricing.yaml` (provider-grouped, with `updated` and
`source` metadata). This module loads them once at import and exposes:

  - `cost_usd(model, usage)` — compute USD cost for a TurnUsage
  - `price_table()` — copy of the loaded table
  - `ModelPrice` — typed entry per model

If your model isn't in the table, `cost_usd` returns 0.0 (silent fallback —
not an error, because some models are free-tier or have unknown pricing).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Any

import yaml  # type: ignore[import-untyped]

from agent_eval.types import TurnUsage


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens for one model."""

    input: float
    output: float
    cache_read: float
    cache_write: float
    provider: str
    updated: str

    @classmethod
    def from_dict(
        cls, name: str, d: dict[str, Any], provider: str, updated: str
    ) -> "ModelPrice":
        return cls(
            input=float(d["input"]),
            output=float(d["output"]),
            # Cache rates fall back to base rates if not separately specified.
            cache_read=float(d.get("cache_read", d["input"])),
            cache_write=float(d.get("cache_write", d["input"])),
            provider=provider,
            updated=updated,
        )


def _load_prices() -> dict[str, ModelPrice]:
    yaml_text = (files("agent_eval") / "data" / "pricing.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(yaml_text)
    out: dict[str, ModelPrice] = {}
    for provider, block in (data.get("providers") or {}).items():
        updated = str(block.get("updated", ""))
        for name, entry in (block.get("models") or {}).items():
            out[name] = ModelPrice.from_dict(name, entry, provider=provider, updated=updated)
    return out


PRICES: dict[str, ModelPrice] = _load_prices()


def price_table() -> dict[str, ModelPrice]:
    """Return a copy of the loaded price table."""
    return dict(PRICES)


def cost_usd(model: str, usage: TurnUsage) -> float:
    """Compute total USD cost for one TurnUsage block. Returns 0.0 for unpriced models."""
    p = PRICES.get(model)
    if p is None:
        return 0.0
    return (
        usage.input_tokens * p.input / 1_000_000
        + usage.output_tokens * p.output / 1_000_000
        + usage.cache_read_tokens * p.cache_read / 1_000_000
        + usage.cache_creation_tokens * p.cache_write / 1_000_000
    )
