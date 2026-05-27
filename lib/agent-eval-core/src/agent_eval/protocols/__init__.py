"""Backend abstraction for "ask the model for structured actions".

See `types.py` for the contract and rationale.

Public surface:
    ToolSpec, ActionResponse, ToolBackend
    NativeToolUseBackend     — provider tool_use API, tool_choice=auto
    SchemaEnforcedBackend    — provider tool_use API, tool_choice=any (forced)
    PromptJSONBackend        — text-only fenced JSON + mimicry detection
"""

from .native import NativeToolUseBackend
from .prompt_json import PromptJSONBackend
from .schema import SchemaEnforcedBackend
from .types import ActionResponse, ToolBackend, ToolSpec

__all__ = [
    "ActionResponse",
    "NativeToolUseBackend",
    "PromptJSONBackend",
    "SchemaEnforcedBackend",
    "ToolBackend",
    "ToolSpec",
]
