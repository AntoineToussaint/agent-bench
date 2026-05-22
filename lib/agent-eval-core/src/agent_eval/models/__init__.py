"""Model client factory + registry.

Usage:
    from agent_eval.models import make_client, MODELS
    print(MODELS)  # all registered model ids
    client = make_client("claude-sonnet-4-6")
    client.reset("you are a helpful assistant")
    client.add_user_text("hi")
    msg = client.step(tools=[])
"""

from __future__ import annotations

from agent_eval.models.anthropic_client import (
    ANTHROPIC_MODELS,
    make_anthropic_client,
)
from agent_eval.models.openai_client import OPENAI_MODELS, make_openai_client
from agent_eval.models.openrouter_client import (
    OPENROUTER_MODELS,
    make_openrouter_client,
)
from agent_eval.types import ModelClient


MODELS: dict[str, str] = {**ANTHROPIC_MODELS, **OPENAI_MODELS, **OPENROUTER_MODELS}


def make_client(model: str) -> ModelClient:
    """Create a provider-specific ModelClient for the named model.

    Raises KeyError if the model isn't registered.
    """
    if model in ANTHROPIC_MODELS:
        client = make_anthropic_client(ANTHROPIC_MODELS[model])
    elif model in OPENAI_MODELS:
        client = make_openai_client(OPENAI_MODELS[model])
    elif model in OPENROUTER_MODELS:
        client = make_openrouter_client(OPENROUTER_MODELS[model])
    else:
        raise KeyError(f"unknown model: {model!r} (registered: {sorted(MODELS)})")
    client.name = model
    return client


__all__ = ["MODELS", "make_client"]
