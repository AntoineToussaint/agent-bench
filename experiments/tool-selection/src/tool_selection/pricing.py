"""Per-model pricing in USD per 1M tokens. As of May 2026.

These are used only for cost telemetry — accuracy here doesn't affect the
benchmark's correctness numbers, only the reported $/query.
"""

from __future__ import annotations

# (input_per_M, output_per_M) in USD
PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-7": (15.00, 75.00),
    # OpenAI
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4": (5.00, 20.00),
    # Embeddings (input only)
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}


def cost_for(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICING:
        return 0.0
    inp, out = PRICING[model]
    return (input_tokens / 1_000_000) * inp + (output_tokens / 1_000_000) * out
