"""Context-engineering policies — control what the model sees each turn.

See `HARNESS.md` for the research motivation. The Protocol mirrors
`ToolBackend`: bundled onto `ModelHandle`, called by the trial loop
before each `step()`.

Public surface:
    ContextPolicy           — the abstract Protocol
    KeepEverything          — baseline (current behavior)
    ToolResultElision       — replace older tool_results with placeholders
    SlidingWindow           — drop turns older than n past the initial user
"""

from .keep_everything import KeepEverything
from .sliding_window import SlidingWindow
from .tool_result_elision import ToolResultElision
from .types import ContextPolicy

__all__ = [
    "ContextPolicy",
    "KeepEverything",
    "SlidingWindow",
    "ToolResultElision",
]
