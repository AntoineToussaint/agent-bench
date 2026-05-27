"""Model registry: bind a model id to its preferred ToolBackend.

`make_model(name)` is the high-level constructor. It builds a
`ModelHandle` = `ModelClient + ToolBackend`. The backend defaults come
from `data/model_backends.yaml` — that file is the authoritative
"empirical recommendation table" we populate as we run comparisons.

For research runs that want to compare backends ON THE SAME model,
pass `backend=...` explicitly:

    handle = make_model("claude-haiku-4-5")                # default backend
    handle = make_model("claude-haiku-4-5",
                        backend=PromptJSONBackend())       # research override
"""

from __future__ import annotations

import functools
from importlib import resources

import yaml

from agent_eval.context import ContextPolicy, KeepEverything
from agent_eval.models import make_client
from agent_eval.protocols import (
    NativeToolUseBackend,
    PromptJSONBackend,
    SchemaEnforcedBackend,
    ToolBackend,
)
from agent_eval.types import ModelHandle


# Backend name → constructor. Adding a new backend means: add it here,
# add its short name to data/model_backends.yaml, and you're done.
_BACKEND_FACTORIES: dict[str, type[ToolBackend]] = {  # type: ignore[type-abstract]
    "native": NativeToolUseBackend,
    "schema": SchemaEnforcedBackend,
    "prompt_json": PromptJSONBackend,
}


@functools.lru_cache(maxsize=1)
def _load_defaults() -> dict[str, str]:
    """Parse data/model_backends.yaml once. Returns model_id → backend_name."""
    text = (
        resources.files("agent_eval.data")
        .joinpath("model_backends.yaml")
        .read_text(encoding="utf-8")
    )
    doc = yaml.safe_load(text) or {}
    table = doc.get("defaults", {})
    if not isinstance(table, dict):
        raise ValueError("model_backends.yaml: `defaults` must be a mapping")
    return {str(k): str(v) for k, v in table.items()}


def default_backend_for(model: str) -> ToolBackend:
    """Look up the recommended backend for `model`.

    Falls back to the `default` entry in the YAML if the model id isn't
    listed. Raises if even `default` is missing or names an unknown
    backend (configuration bug — fail loud).
    """
    table = _load_defaults()
    name = table.get(model, table.get("default"))
    if name is None:
        raise KeyError(
            f"No default backend for {model!r} and no `default` entry "
            f"in model_backends.yaml"
        )
    if name not in _BACKEND_FACTORIES:
        raise KeyError(
            f"Unknown backend name {name!r} in model_backends.yaml. "
            f"Valid: {sorted(_BACKEND_FACTORIES)}"
        )
    return _BACKEND_FACTORIES[name]()


def make_model(
    model: str,
    *,
    backend: ToolBackend | None = None,
    context_policy: ContextPolicy | None = None,
) -> ModelHandle:
    """Build a `ModelHandle` for `model`.

    Args:
        model: identifier understood by `make_client`.
        backend: optional override. None = use the recommended default
            from `data/model_backends.yaml`.
        context_policy: optional context-engineering policy. None =
            KeepEverything (full-history replay; the existing behavior).
            See `lib/agent-eval-core/HARNESS.md` for the rationale.
    """
    client = make_client(model)
    if backend is None:
        backend = default_backend_for(model)
    if context_policy is None:
        context_policy = KeepEverything()
    return ModelHandle(client=client, backend=backend, context_policy=context_policy)


__all__ = ["default_backend_for", "make_model"]
