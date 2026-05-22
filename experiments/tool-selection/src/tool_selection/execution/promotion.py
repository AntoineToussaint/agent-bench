"""Phase 3: lesson promotion to derived tools.

When the same failure-correction lesson recurs across N episodes (default N=2),
synthesize a derived tool that encodes the fix structurally. The derived tool
wraps a source primitive (e.g. `bash`) with arg-transformation logic that
makes the failure impossible.

Two synthesizers are available:
- `synth_pytest_run`: hand-templated reference for the pytest-in-verify/ case.
  Useful as a smoke test of the architecture and as a fallback when the LLM
  synthesizer fails.
- `LLMSynthesizer`: takes a cluster of lessons + source tool spec and asks
  Sonnet 4.6 to produce a structured DerivedToolSpec (name, description,
  schema, wrap_template). The template is parsed safely — no arbitrary
  code eval; just Python str.format with optional conditional renders.

Promotion semantics:
  - LessonCluster: lessons sharing (tool, error_signature). The cluster has
    a 'count' that increments each time a matching lesson is added.
  - Promotion threshold: count >= N triggers synthesis.
  - Once promoted, the LessonStore marks the cluster as 'crystallized' so
    the same lessons don't promote again.
  - The derived tool is added to the experiment's surfaced catalog for
    subsequent episodes.
  - When the derived tool is called, the executor translates its args back
    to the source tool's args and executes through the source tool's
    failure-trigger gauntlet. Because the args have been corrected,
    the failure trigger no longer fires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from tool_selection.types import Tool

from .lessons import Lesson


# ---------- DerivedTool: wraps a source tool with arg-fixing logic ----------


@dataclass
class DerivedTool:
    """A tool synthesized from recurring lesson clusters."""

    tool: Tool
    """The Tool spec the model sees (name, description, schema)."""

    source_tool_name: str
    """The primitive this derived tool wraps (e.g., 'bash')."""

    wrap_fn: Callable[[dict[str, Any]], dict[str, Any]]
    """Translates derived-tool args → source-tool args. The wrapped args
    are what gets executed (and what failure_triggers inspect)."""

    source_lessons: list[str] = field(default_factory=list)
    """IDs of the lessons this derived tool subsumes — used to retire them."""


# ---------- Hand-templated synthesizers ----------


def _synthesize_pytest_run() -> DerivedTool:
    """The canonical promotion for our experiment: 'pytest goes in verify/'.

    The derived tool takes `test_path` (relative to the project's test
    directory, no prefix) and produces a bash command with the correct
    prefix baked in.
    """
    tool = Tool(
        name="pytest_run",
        toolbox="filesystem",
        description=(
            "Run pytest in this project. The test directory's path prefix is "
            "handled for you — just pass the test file path relative to the "
            "test directory.\n\n"
            "Example:\n"
            "  pytest_run(test_path='test_auth.py')  # runs the auth tests\n"
            "  pytest_run(test_path='test_auth.py::test_login', verbose=True)"
        ),
        json_schema={
            "type": "object",
            "properties": {
                "test_path": {
                    "type": "string",
                    "description": "Test file or pytest node-id relative to the test dir (no path prefix needed).",
                },
                "verbose": {"type": "boolean"},
            },
            "required": ["test_path"],
            "additionalProperties": False,
        },
    )

    def wrap_fn(args: dict[str, Any]) -> dict[str, Any]:
        # Strip any path prefix the model accidentally included
        path = (args.get("test_path") or "").lstrip("/")
        for prefix in ("verify/", "tests/", "test/"):
            if path.startswith(prefix):
                path = path[len(prefix):]
                break
        # Always prepend the project-specific prefix
        wrapped_path = f"verify/{path}"
        verbose = " -v" if args.get("verbose") else ""
        return {"command": f"pytest {wrapped_path}{verbose}"}

    return DerivedTool(tool=tool, source_tool_name="bash", wrap_fn=wrap_fn)


# ---------- LessonCluster + PromotionPolicy ----------


@dataclass
class LessonCluster:
    """A group of lessons that share a failure family."""

    key: str
    """Identifier: '<source_tool>:<failure_category>:<error_signature>'."""

    lessons: list[Lesson] = field(default_factory=list)
    crystallized: bool = False
    """True once promoted to a derived tool — further lessons in this cluster
    don't re-promote."""


def _cluster_key(lesson: Lesson) -> str:
    """Cluster lessons by (tool, category, error fingerprint).

    The error fingerprint is the first 60 characters of source_error
    (normalized whitespace), which is enough to distinguish 'collected 0 items'
    (pytest path failure) from 'command not found' (path-to-script failure)
    even when both go through bash + wrong-state.
    """
    fp = " ".join((lesson.source_error or "").split())[:60]
    return f"{lesson.key}:{lesson.category}:{fp}"


def _pick_synthesizer(cluster: LessonCluster) -> DerivedTool | None:
    """For v1 we recognize specific failure patterns by source-tool + category
    + a substring match on the error text. Returns None if no synthesizer
    matches — the cluster doesn't promote in that case.

    Production version would call an LLM here.
    """
    if not cluster.lessons:
        return None
    sample = cluster.lessons[0]
    # Pattern: bash + wrong-state + pytest-related lesson text
    if (
        sample.scope == "tool"
        and sample.key == "bash"
        and sample.category == "wrong-state"
        and any(kw in sample.text.lower() or kw in sample.source_error.lower()
                for kw in ["pytest", "verify/", "tests/", "collected 0 items"])
    ):
        return _synthesize_pytest_run()
    return None


@dataclass
class PromotionManager:
    """Owns the lesson-to-derived-tool promotion lifecycle.

    Add lessons via `add_lesson()`; if any cluster crosses the threshold,
    promote and return the new DerivedTool. Track all derived tools so
    they can be injected into the catalog for subsequent episodes.

    Two synthesis paths:
      - `synthesizer='hand'` (default for backwards compat): _pick_synthesizer
        recognizes specific patterns (pytest in verify/) and emits a
        hand-written DerivedTool.
      - `synthesizer='llm'`: call execution.synthesizer.synthesize_from_cluster
        which uses Sonnet to design a derived tool from arbitrary lesson
        clusters. Requires `source_tool_resolver(name) -> Tool` to look up
        the source tool spec at promotion time.
    """

    threshold: int = 2
    synthesizer: str = "hand"  # 'hand' | 'llm'
    source_tool_resolver: Any = None  # Callable[[str], Tool | None]
    synth_cost_usd: float = 0.0  # cumulative cost of LLM synthesis calls

    clusters: dict[str, LessonCluster] = field(default_factory=dict)
    derived_tools: list[DerivedTool] = field(default_factory=list)

    def add_lesson(self, lesson: Lesson) -> DerivedTool | None:
        """Add a lesson, returning a newly-promoted DerivedTool or None."""
        ck = _cluster_key(lesson)
        cluster = self.clusters.setdefault(ck, LessonCluster(key=ck))
        if cluster.crystallized:
            return None

        if not any(existing.text == lesson.text for existing in cluster.lessons):
            cluster.lessons.append(lesson)

        if len(cluster.lessons) >= self.threshold:
            synth = self._promote_cluster(cluster)
            if synth is not None:
                synth.source_lessons = [l.id for l in cluster.lessons]
                cluster.crystallized = True
                self.derived_tools.append(synth)
                return synth
        return None

    def _promote_cluster(self, cluster: LessonCluster) -> DerivedTool | None:
        if self.synthesizer == "llm" and self.source_tool_resolver is not None:
            return self._llm_promote(cluster)
        return _pick_synthesizer(cluster)

    def _llm_promote(self, cluster: LessonCluster) -> DerivedTool | None:
        if not cluster.lessons:
            return None
        from .synthesizer import synthesize_from_cluster

        source_tool_name = cluster.lessons[0].key
        source_tool = self.source_tool_resolver(source_tool_name) if self.source_tool_resolver else None
        if source_tool is None:
            return None
        result = synthesize_from_cluster(cluster.lessons, source_tool)
        self.synth_cost_usd += result.cost_usd
        return result.derived
