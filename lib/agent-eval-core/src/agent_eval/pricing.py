"""Per-model token pricing in USD per million tokens.

Last updated: 2026-01. Update when providers change prices.
Source: https://platform.claude.com/docs/about-claude/pricing  and OpenAI pricing page.
"""

from __future__ import annotations

from agent_eval.types import TurnUsage


# (input_per_mtok, output_per_mtok, cache_read_per_mtok, cache_write_per_mtok)
# cache values default to input/output when not separately priced.
PRICES_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    # Anthropic — Claude 4.x family
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
    "claude-haiku-4-5-20251001": (1.00, 5.00, 0.10, 1.25),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30, 3.75),
    "claude-opus-4-7": (15.00, 75.00, 1.50, 18.75),
    # OpenAI — GPT-5 family
    "gpt-5": (1.25, 10.00, 0.13, 1.25),
    "gpt-5-mini": (0.25, 2.00, 0.025, 0.25),
    # Via OpenRouter (prices fetched 2026-05; OpenRouter passes through
    # provider pricing plus ~5% margin. Check openrouter.ai/models for current.)
    "gemini-2.5-pro": (1.25, 10.00, 1.25, 1.25),
    "gemini-2.5-flash": (0.30, 2.50, 0.30, 0.30),
    "grok-4": (3.00, 15.00, 3.00, 3.00),
    "grok-4-fast": (0.20, 0.50, 0.20, 0.20),
    "deepseek-v3.1": (0.27, 1.10, 0.07, 0.27),
    "deepseek-r1": (0.55, 2.19, 0.14, 0.55),
    "llama-4-scout": (0.18, 0.59, 0.18, 0.18),
    "llama-4-maverick": (0.35, 1.40, 0.35, 0.35),
    "qwen-3-coder": (0.40, 1.60, 0.40, 0.40),
}


def price_table() -> dict[str, tuple[float, float, float, float]]:
    """Return a copy of the per-Mtok price table."""
    return dict(PRICES_PER_MTOK)


def cost_usd(model: str, usage: TurnUsage) -> float:
    """Compute total USD cost for one TurnUsage block."""
    if model not in PRICES_PER_MTOK:
        return 0.0
    in_price, out_price, cache_read_price, cache_write_price = PRICES_PER_MTOK[model]
    # Input tokens billed at standard rate; cache reads/writes at their own rates.
    base_input = usage.input_tokens
    cache_read = usage.cache_read_tokens
    cache_write = usage.cache_creation_tokens
    output = usage.output_tokens

    return (
        base_input * in_price / 1_000_000
        + output * out_price / 1_000_000
        + cache_read * cache_read_price / 1_000_000
        + cache_write * cache_write_price / 1_000_000
    )
