"""Composable pipeline stages.

A Stage takes the current candidate Tool list and narrows it. Stages can be
chained: e.g. a toolbox-routing stage followed by an in-toolbox tool-selection
stage. Each stage produces a PipelineStep for cost/latency accounting.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from tool_selection.selectors.base import Selector
from tool_selection.types import Catalog, PipelineStep, Task, Tool, Toolbox


def _query_for(task: Task) -> str:
    return f"{task.prompt}\n\n{task.context}"


@dataclass
class StageOutput:
    tools: list[Tool]
    steps: list[PipelineStep]


class Stage(ABC):
    id: str

    @abstractmethod
    def reduce(self, tools: list[Tool], task: Task, catalog: Catalog) -> StageOutput: ...


class ToolboxStage(Stage):
    """Restrict to tools belonging to the top-k toolboxes (by selector score)."""

    def __init__(self, selector: Selector, k: int = 2):
        self.selector = selector
        self.k = k
        self.id = f"tb:{selector.id}/k={k}"

    def reduce(self, tools: list[Tool], task: Task, catalog: Catalog) -> StageOutput:
        # Build the toolbox candidate list from the toolboxes currently
        # represented in `tools` (so cascading stages narrow correctly).
        present_names: list[str] = []
        for t in tools:
            if t.toolbox not in present_names:
                present_names.append(t.toolbox)
        candidates: list[Toolbox] = [tb for tb in catalog.toolboxes if tb.name in present_names]

        if len(candidates) <= self.k:
            # No filtering needed; just record a no-op step
            return StageOutput(
                tools=tools,
                steps=[
                    PipelineStep(
                        kind="embedding" if "embed" in self.selector.id or "bm25" in self.selector.id else "llm_router",
                        model=self.selector.id,
                        note=f"toolbox stage no-op (have {len(candidates)} ≤ k={self.k})",
                    )
                ],
            )

        sel = self.selector.select(_query_for(task), candidates, self.k)
        chosen = set(sel.selected_ids)
        narrowed = [t for t in tools if t.toolbox in chosen]
        return StageOutput(tools=narrowed, steps=list(sel.steps))


class ToolStage(Stage):
    """Restrict the candidate Tool list to the top-k (by selector score)."""

    def __init__(self, selector: Selector, k: int = 10):
        self.selector = selector
        self.k = k
        self.id = f"tool:{selector.id}/k={k}"

    def reduce(self, tools: list[Tool], task: Task, catalog: Catalog) -> StageOutput:
        if len(tools) <= self.k:
            return StageOutput(
                tools=tools,
                steps=[
                    PipelineStep(
                        kind="embedding" if "embed" in self.selector.id or "bm25" in self.selector.id else "llm_router",
                        model=self.selector.id,
                        note=f"tool stage no-op (have {len(tools)} ≤ k={self.k})",
                    )
                ],
            )
        sel = self.selector.select(_query_for(task), tools, self.k)
        chosen = set(sel.selected_ids)
        narrowed = [t for t in tools if t.name in chosen]
        return StageOutput(tools=narrowed, steps=list(sel.steps))
