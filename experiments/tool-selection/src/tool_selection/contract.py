"""Canonical contract types for the tool-selection experiment.

This module is the source-of-truth import path for the types every trial
must consume/produce. They're defined in `types.py` and re-exported here
to match the standard `contract.py + adapters/ + CONTRACT.md` layout used
across `agent-bench`.

See CONTRACT.md for the prose spec.
"""

from tool_selection.types import (  # noqa: F401
    Catalog,
    CallTrace,
    Granularity,
    PipelineStep,
    RequiredCall,
    ScoreCard,
    Task,
    Tool,
    Toolbox,
)

__all__ = [
    "Catalog",
    "CallTrace",
    "Granularity",
    "PipelineStep",
    "RequiredCall",
    "ScoreCard",
    "Task",
    "Tool",
    "Toolbox",
]
