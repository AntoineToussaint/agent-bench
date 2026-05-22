"""CompositeApproach: run an ordered list of Stages, then surface the result."""

from __future__ import annotations

from tool_selection.types import Catalog, Task

from .base import Approach, ApproachResult
from .stages import Stage


class CompositeApproach(Approach):
    def __init__(self, id: str, stages: list[Stage]):
        self.id = id
        self.stages = stages

    def surface(self, task: Task, catalog: Catalog) -> ApproachResult:
        tools = list(catalog.all_tools)
        all_steps = []
        for stage in self.stages:
            out = stage.reduce(tools, task, catalog)
            tools = out.tools
            all_steps.extend(out.steps)
        return ApproachResult(surfaced_tools=tools, pre_steps=all_steps)
