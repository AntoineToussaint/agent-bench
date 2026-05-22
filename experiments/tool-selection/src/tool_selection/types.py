"""Core data model for the one-shot tool-selection benchmark.

Vocabulary:
- Tool: a single callable surface with a JSON schema. Belongs to one Toolbox.
- Toolbox: a named group of tools (e.g. "git") with its own description.
- Catalog: the full set of toolboxes, in one of two granularities (narrow vs fat).
- Task: a user-facing instruction that requires a specific succession of tool calls.
- RequiredCall: a constraint over a single tool_use in the model's response.
- PipelineStep: one inner step in an approach's pipeline (LLM router, embedding, etc.).
- CallTrace: the full record of one (approach × model × task) run.
- ScoreCard: the structural score of a CallTrace against its Task's rubric.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    json_schema: dict[str, Any]
    toolbox: str

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.json_schema,
        }

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.json_schema,
            },
        }


@dataclass(frozen=True)
class Toolbox:
    name: str
    description: str
    tools: tuple[Tool, ...]


Granularity = Literal["narrow", "fat", "narrow-rich", "fat-rich", "narrow-rich-80", "narrow-rich-150", "primitive"]
"""Catalog flavor. The dimension encodes both tool granularity (narrow/fat) and
description-richness/size axes for brevity:
- 'narrow' vs 'fat': how many tools cover the same capabilities (~40 vs ~12).
- 'thin' (default) vs 'rich': per-tool description length and per-arg docs.
  Rich variants ('narrow-rich', 'fat-rich') mimic production MCP servers
  (e.g. GitHub MCP) with multi-paragraph descriptions.
- '-80' / '-150' suffixes: rich-description catalogs padded with realistic
  distractor tools to ~80 (real GitHub MCP scale) or ~150 (multi-MCP setup).
  Anchor tools (39 from narrow_rich) that the benchmark tasks reference are
  always present; the padding measures the 'tool surface tax' as catalog grows."""


@dataclass(frozen=True)
class Catalog:
    granularity: Granularity
    toolboxes: tuple[Toolbox, ...]

    @property
    def all_tools(self) -> tuple[Tool, ...]:
        return tuple(t for tb in self.toolboxes for t in tb.tools)

    def get_tool(self, name: str) -> Tool | None:
        for t in self.all_tools:
            if t.name == name:
                return t
        return None

    def get_toolbox(self, name: str) -> Toolbox | None:
        for tb in self.toolboxes:
            if tb.name == name:
                return tb
        return None


@dataclass(frozen=True)
class RequiredCall:
    """One required tool_use block in the model's final response.

    Authored in terms of a granularity-agnostic operation name (e.g. 'git.commit').
    The scorer resolves the op against the catalog being evaluated and matches
    `args` entries against the model's tool_use input.

    - op: a key in OPERATIONS (operations.py).
    - args: mapping of arg-key → Matcher (Eq/Regex/Contains/Present/OneOf).
      Bare values are coerced to Eq. The matchers run against the model's
      input dict for the tool_use. Args from the op's granularity translation
      (e.g. action='commit' for fat) are added automatically; tasks don't
      need to repeat them.
    """

    op: str
    args: dict[str, Any] = field(default_factory=dict)
    note: str = ""


Difficulty = Literal["small", "medium", "large"]  # 1-3 / 4-7 / 8+ required calls


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    """The user-facing instruction the model receives."""

    context: str
    """Pre-surfaced context (file contents, diffs, branch state). Keeps the task
    one-shot — the model doesn't need to call read-tools to discover state."""

    difficulty: Difficulty
    required_calls: tuple[RequiredCall, ...]
    """The minimal set of calls that must appear (order-insensitive by default;
    set strict_order=True to require them in declaration order)."""

    strict_order: bool = False
    """If True, the model's tool_use sequence must contain the required calls
    in the order they appear in required_calls (other calls may interleave)."""

    expected_toolboxes: tuple[str, ...] = ()
    """Ground truth for toolbox-preselection scoring. Derived from required_calls
    if empty (in tasks/__init__.py)."""

    forbidden_ops: tuple[str, ...] = ()
    """Operations that should NOT be called. Used for clearly-wrong alternatives
    (e.g. forbid gh.pr_comment when the task asks for an inline review comment)."""

    failure_triggers: tuple = ()
    """Tuple of `execution.FailureTrigger` for multi-turn episode runs. Each
    trigger fires deterministically when its predicate matches an in-flight
    call + the agent's history, returning a realistic error string instead of
    success. Tasks without failure_triggers run identically in single-shot and
    multi-turn modes (the trigger list is empty so every call 'succeeds')."""

    note: str = ""


@dataclass
class PipelineStep:
    """One inner step of an approach's pipeline (before the final tool-calling shot)."""

    kind: Literal["embedding", "llm_router", "final_shot"]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    """Wall-clock time for THIS API call alone."""
    note: str = ""
    parallel_group: int | None = None
    """If set, this step ran in parallel with all other steps sharing the same
    parallel_group id. The trace's wall-clock latency uses max(latency_ms)
    over each group, not sum. None = sequential (counts toward sum)."""


@dataclass
class CallTrace:
    """Full record of one (approach × model × task) run."""

    task_id: str
    approach_id: str
    granularity: Granularity
    final_model: str
    surfaced_tools: list[str]
    """Tool names actually surfaced to the final shot."""

    final_calls: list[dict[str, Any]]
    """The model's tool_use blocks from the final shot, normalized to
    {name, input} dicts."""

    final_text: str = ""
    """Any free-text the model produced alongside tool calls."""

    pipeline: list[PipelineStep] = field(default_factory=list)
    error: str | None = None

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.pipeline)

    @property
    def total_latency_ms(self) -> float:
        """Wall-clock latency. Sequential steps add up; steps sharing a
        parallel_group id collapse to max(latency) within the group."""
        sequential = sum(s.latency_ms for s in self.pipeline if s.parallel_group is None)
        groups: dict[int, list[float]] = {}
        for s in self.pipeline:
            if s.parallel_group is not None:
                groups.setdefault(s.parallel_group, []).append(s.latency_ms)
        parallel = sum(max(latencies) for latencies in groups.values())
        return sequential + parallel

    @property
    def total_sequential_latency_ms(self) -> float:
        """The sum-of-all-API-call latencies (what you'd get without parallelism).
        Useful as an upper bound and for debugging."""
        return sum(s.latency_ms for s in self.pipeline)

    @property
    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.pipeline)

    @property
    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.pipeline)


@dataclass
class ScoreCard:
    task_id: str
    approach_id: str
    granularity: Granularity
    final_model: str

    required_total: int
    required_matched: int
    """Required calls where SOME emitted call matched on (tool name + op
    discriminator args + task-level arg matchers). 'Strict' matching — the
    legacy score from before decomposition. Equivalent to the new
    `args_matched_strict` view."""

    missing_required: list[str]
    """Op names of required calls that did not appear or appeared with wrong args."""

    hallucinated_calls: list[str]
    """Tool names called that were not in the surfaced set."""

    extra_calls: list[str]
    """Calls to surfaced tools that weren't required and weren't forbidden
    (mild noise, not failure)."""

    forbidden_called: list[str]
    """Tool names called that resolved to a forbidden_op."""

    schema_invalid_calls: list[str]
    """Tool names whose input failed schema validation (missing required arg,
    unknown arg, or wrong type)."""

    selection_matched: int = 0
    """Decomposed view: required calls where SOME emitted call matched on
    (tool name + op discriminator args), regardless of whether task-level
    arg matchers (message text, line number, etc.) were satisfied. Always
    >= required_matched. Set by scorer's second pass.

    Use selection_matched/required_total for 'did the model pick the right
    tool?'. Use required_matched/required_total for 'did it pick the right
    tool AND call it with the right args?'. The gap = args-construction
    errors given correct selection."""

    @property
    def task_success(self) -> bool:
        return (
            self.required_matched == self.required_total
            and not self.hallucinated_calls
            and not self.forbidden_called
            and not self.schema_invalid_calls
        )

    @property
    def required_recall(self) -> float:
        return self.required_matched / self.required_total if self.required_total else 1.0

    @property
    def selection_accuracy(self) -> float:
        """Fraction of required calls where the right tool was picked
        (args may or may not be right)."""
        return self.selection_matched / self.required_total if self.required_total else 1.0

    @property
    def args_accuracy_given_selection(self) -> float:
        """Of the required calls where selection was correct, the fraction
        that ALSO had correct args. The 'arg construction quality' axis."""
        if self.selection_matched == 0:
            return 0.0
        return self.required_matched / self.selection_matched
