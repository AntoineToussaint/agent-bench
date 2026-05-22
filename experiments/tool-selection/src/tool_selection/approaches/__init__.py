"""Tool-surfacing approaches.

The canonical approach is `CompositeApproach`, which runs an ordered list of
`Stage` instances and surfaces the resulting tools to the final shot.
`FullApproach` is the special case with zero stages (whole catalog upfront).

Strategies — the concrete configurations we benchmark — are defined in
`tool_selection.strategies`. Use `build_strategy(strategy_id)` to get an
Approach instance.
"""

from .base import Approach, ApproachResult
from .composite import CompositeApproach
from .full import FullApproach
from .stages import Stage, StageOutput, ToolboxStage, ToolStage

__all__ = [
    "Approach",
    "ApproachResult",
    "FullApproach",
    "CompositeApproach",
    "Stage",
    "StageOutput",
    "ToolboxStage",
    "ToolStage",
]
