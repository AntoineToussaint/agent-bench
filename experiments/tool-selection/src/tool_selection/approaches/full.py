"""Full-tools-upfront baseline: surface every tool in the catalog."""

from __future__ import annotations

from tool_selection.types import Catalog, Task

from .base import Approach, ApproachResult


class FullApproach(Approach):
    id = "full"

    def surface(self, task: Task, catalog: Catalog) -> ApproachResult:
        return ApproachResult(
            surfaced_tools=list(catalog.all_tools),
            pre_steps=[],  # no inner pipeline
        )
