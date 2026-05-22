"""Description augmenter — the lighter alternative to derived-tool promotion.

Instead of minting a new tool from recurring lessons, append a "Known gotchas"
addendum to the SOURCE tool's description. The model just sees a richer
description of the tool it was already going to use.

Why this is lighter than promotion:
  - No catalog pollution: API surface stays stable, no risk of model picking
    a wrong sibling tool.
  - Reversible: drop the addendum and the description reverts to baseline.
  - No wrap_fn: the LLM can't synthesize a bad arg-translation that fails
    silently.
  - Robust to over-specific synthesis: even a too-narrow addendum ("for build
    tasks, use ./tools/run build") still gives the model a useful seed.

The augmenter shares the cluster-and-promote plumbing with PromotionManager
but the synthesis output is a string (text to append) rather than a Tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from agent_eval import make_client

from tool_selection.pricing import cost_for
from tool_selection.types import Tool

from .lessons import Lesson
from .promotion import LessonCluster, _cluster_key, _pick_synthesizer  # reuse clustering

load_dotenv()


@dataclass
class DescriptionPatch:
    target_tool: str
    """The source tool whose description we augment."""

    addendum: str
    """Text appended to the source tool's description."""

    source_lessons: list[str] = field(default_factory=list)


AUGMENT_SYSTEM = """\
You write a short DOCUMENTATION ADDENDUM for a tool, distilled from recurring
failures the agent has experienced when using it. The addendum will be APPENDED
to the tool's existing description — keep it concise (2-5 sentences), specific,
and actionable.

Goal: a future agent reading the tool's description will know to avoid the
recurring failure mode without you having to inject lessons elsewhere.

Format your addendum as a "Known gotchas" or "Project conventions" section.
Use plain markdown. Example:

  Known gotchas in this repo:
  - This project uses `verify/` as its pytest test directory (not `tests/`).
    Always run `pytest verify/<test_file>` not `pytest <test_file>` or
    `pytest tests/<test_file>`.
  - Common composition error: omitting the `verify/` prefix returns
    'collected 0 items'.

Output the addendum text ONLY (no JSON, no headers, no commentary). Start
with a clear section heading like "Known gotchas:" or "Project conventions:".
"""


@dataclass
class AugmentResult:
    patch: DescriptionPatch | None
    error: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


def synthesize_patch(
    cluster_lessons: list[Lesson],
    source_tool: Tool,
    model: str = "claude-sonnet-4-6",
) -> AugmentResult:
    """Ask the LLM for a description addendum encoding the recurring lesson."""
    if not cluster_lessons:
        return AugmentResult(patch=None, error="empty cluster")

    lesson_block = "\n".join(
        f"  - [{l.category}] {l.text}\n      (from error: {l.source_error[:150]})"
        for l in cluster_lessons
    )
    prompt = (
        f"# Source tool\n"
        f"name: {source_tool.name}\n"
        f"current description:\n{source_tool.description}\n\n"
        f"# Recurring failures ({len(cluster_lessons)} fires)\n"
        f"{lesson_block}\n\n"
        f"Write the addendum (start with a clear section heading)."
    )

    try:
        client = make_client(model)
        if hasattr(client, "max_tokens"):
            client.max_tokens = 400
        client.reset(AUGMENT_SYSTEM)
        client.add_user_text(prompt)
        msg = client.step([])
        text = msg.text.strip()
        in_tok = msg.usage.input_tokens
        out_tok = msg.usage.output_tokens
    except Exception as exc:  # noqa: BLE001
        return AugmentResult(patch=None, error=f"api error: {exc!r}")

    cost = cost_for(model, in_tok, out_tok)
    if not text:
        return AugmentResult(patch=None, error="empty addendum", cost_usd=cost,
                             input_tokens=in_tok, output_tokens=out_tok)

    patch = DescriptionPatch(
        target_tool=source_tool.name,
        addendum=text,
        source_lessons=[l.id for l in cluster_lessons],
    )
    return AugmentResult(patch=patch, cost_usd=cost, input_tokens=in_tok, output_tokens=out_tok)


@dataclass
class AugmentationManager:
    """Like PromotionManager but produces description patches instead of derived tools."""

    threshold: int = 1
    source_tool_resolver: Any = None  # Callable[[str], Tool | None]
    synth_cost_usd: float = 0.0

    clusters: dict[str, LessonCluster] = field(default_factory=dict)
    patches: dict[str, list[DescriptionPatch]] = field(default_factory=dict)
    """tool_name → list of accumulated addenda."""

    def add_lesson(self, lesson: Lesson) -> DescriptionPatch | None:
        ck = _cluster_key(lesson)
        cluster = self.clusters.setdefault(ck, LessonCluster(key=ck))
        if cluster.crystallized:
            return None
        if not any(existing.text == lesson.text for existing in cluster.lessons):
            cluster.lessons.append(lesson)
        if len(cluster.lessons) >= self.threshold:
            if self.source_tool_resolver is None:
                return None
            source = self.source_tool_resolver(lesson.key)
            if source is None:
                return None
            result = synthesize_patch(cluster.lessons, source)
            self.synth_cost_usd += result.cost_usd
            if result.patch is not None:
                cluster.crystallized = True
                self.patches.setdefault(result.patch.target_tool, []).append(result.patch)
                return result.patch
        return None


def apply_patches_to_tool(tool: Tool, patches: list[DescriptionPatch]) -> Tool:
    """Return a copy of `tool` with all patch addenda appended to its description."""
    if not patches:
        return tool
    addenda = "\n\n" + "\n\n".join(p.addendum for p in patches)
    return Tool(
        name=tool.name,
        toolbox=tool.toolbox,
        description=tool.description + addenda,
        json_schema=tool.json_schema,
    )
