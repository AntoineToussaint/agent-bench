"""Strategy registry — the concrete pipeline configurations we benchmark.

A strategy is a named ordered list of Stages, instantiated into a
CompositeApproach. The registry lets the runner iterate over a fixed set of
strategies and produces stable IDs that show up in traces and reports.

Strategy families:
  - `full`               : no inner stages; full catalog to final shot
  - `toolbox:<sel>`      : one toolbox stage with selector <sel>, then surface
                           all tools in those toolboxes
  - `tool:<sel>`         : one tool stage with selector <sel>, k=10
  - `hybrid:<a>+<b>`     : two-stage tool retrieval — embedding shortlist (a)
                           then LLM rerank (b). Inspired by the old retrieval
                           study's winner.
  - `cascade:<tb>+<tool>`: toolbox stage (tb) → tool stage (tool). A more
                           aggressive narrowing that combines coarse routing
                           with fine selection.
"""

from __future__ import annotations

from typing import Callable

from .approaches.base import Approach
from .approaches.composite import CompositeApproach
from .approaches.full import FullApproach
from .approaches.stages import Stage, ToolboxStage, ToolStage
from .selectors import get_selector


def _full() -> Approach:
    return FullApproach()


def _toolbox(selector_id: str, k: int = 2) -> Approach:
    return CompositeApproach(
        id=f"toolbox:{selector_id}",
        stages=[ToolboxStage(get_selector(selector_id), k=k)],
    )


def _tool(selector_id: str, k: int = 10) -> Approach:
    return CompositeApproach(
        id=f"tool:{selector_id}",
        stages=[ToolStage(get_selector(selector_id), k=k)],
    )


def _hybrid(first: str, second: str, k1: int = 20, k2: int = 10) -> Approach:
    return CompositeApproach(
        id=f"hybrid:{first}+{second}",
        stages=[
            ToolStage(get_selector(first), k=k1),
            ToolStage(get_selector(second), k=k2),
        ],
    )


def _cascade(toolbox_sel: str, tool_sel: str, k_tb: int = 2, k_tool: int = 10) -> Approach:
    return CompositeApproach(
        id=f"cascade:{toolbox_sel}+{tool_sel}",
        stages=[
            ToolboxStage(get_selector(toolbox_sel), k=k_tb),
            ToolStage(get_selector(tool_sel), k=k_tool),
        ],
    )


# The registry. Each entry is a (lazy) factory so we only construct selectors
# (and their clients) on demand.
STRATEGY_FACTORIES: dict[str, Callable[[], Approach]] = {
    # Baseline
    "full": _full,
    # Single-stage toolbox preselection
    "toolbox:bm25": lambda: _toolbox("bm25"),
    "toolbox:embed-openai-small": lambda: _toolbox("embed-openai-small"),
    "toolbox:llm-haiku": lambda: _toolbox("llm-haiku"),
    # Single-stage tool retrieval
    "tool:bm25": lambda: _tool("bm25"),
    "tool:embed-openai-small": lambda: _tool("embed-openai-small"),
    "tool:llm-haiku": lambda: _tool("llm-haiku"),
    # Hybrid (tool-level cascade: cheap shortlist → expensive rerank)
    "hybrid:embed-openai-small+llm-haiku": lambda: _hybrid("embed-openai-small", "llm-haiku"),
    "hybrid:bm25+llm-haiku": lambda: _hybrid("bm25", "llm-haiku"),
    # Cascade (toolbox routing → in-toolbox tool retrieval)
    "cascade:llm-haiku+bm25": lambda: _cascade("llm-haiku", "bm25"),
    "cascade:embed-openai-small+embed-openai-small": lambda: _cascade(
        "embed-openai-small", "embed-openai-small"
    ),
    "cascade:llm-haiku+embed-openai-small": lambda: _cascade("llm-haiku", "embed-openai-small"),
}


def build_strategy(strategy_id: str) -> Approach:
    if strategy_id not in STRATEGY_FACTORIES:
        raise KeyError(f"unknown strategy: {strategy_id!r}. known: {sorted(STRATEGY_FACTORIES)}")
    return STRATEGY_FACTORIES[strategy_id]()


# Default strategy sweep — what scripts/run_sweep.py iterates over by default.
DEFAULT_SWEEP: tuple[str, ...] = (
    "full",
    "toolbox:bm25",
    "toolbox:embed-openai-small",
    "toolbox:llm-haiku",
    "tool:bm25",
    "tool:embed-openai-small",
    "tool:llm-haiku",
    "hybrid:embed-openai-small+llm-haiku",
    "hybrid:bm25+llm-haiku",
    "cascade:llm-haiku+bm25",
    "cascade:llm-haiku+embed-openai-small",
)
