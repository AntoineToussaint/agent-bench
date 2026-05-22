"""Huge-catalog variants: narrow_rich anchor tools + N realistic distractor tools.

Anchor tools (39, from narrow_rich) are exactly the ones the 16 benchmark tasks
reference. Distractors are GitHub-MCP-style tools that never appear as required
calls; their job is to bloat the candidate surface so the model has to discriminate
against them.

Sizes calibrated to real production:
  - narrow-rich-80  : ~real GitHub MCP scale (post-Jan-2026 reduction = 17.6K
                     tokens of definitions)
  - narrow-rich-150 : multi-MCP user setup (GitHub + Linear + Atlassian + Slack
                     + Notion + Sentry combined)
"""

from __future__ import annotations

from tool_selection.types import Catalog, Toolbox

from ._descriptions import TOOLBOX_DESCRIPTIONS
from ._distractors import DISTRACTOR_POOL
from .narrow_rich import narrow_rich_catalog


def _build_huge(target_size: int, granularity_name: str) -> Catalog:
    """Build a catalog of exactly `target_size` tools by augmenting narrow_rich
    with the first N distractors from the pool. Distractors are inserted into
    their declared toolbox so each toolbox grows realistically."""
    anchor_tools_by_toolbox: dict[str, list] = {tb.name: list(tb.tools) for tb in narrow_rich_catalog.toolboxes}
    n_anchor = sum(len(v) for v in anchor_tools_by_toolbox.values())
    n_needed = target_size - n_anchor
    if n_needed < 0:
        raise ValueError(f"target_size {target_size} < anchor size {n_anchor}")
    if n_needed > len(DISTRACTOR_POOL):
        raise ValueError(
            f"target_size {target_size} would need {n_needed} distractors but pool has only {len(DISTRACTOR_POOL)}"
        )

    # Add distractors in pool order. Pool is intentionally ordered so realistic
    # GitHub-MCP-style additions come first; multi-MCP (Linear/Atlassian/Slack)
    # only appears at the 150-tool size.
    for distractor in DISTRACTOR_POOL[:n_needed]:
        anchor_tools_by_toolbox.setdefault(distractor.toolbox, []).append(distractor)

    toolboxes = tuple(
        Toolbox(
            name=tb_name,
            description=TOOLBOX_DESCRIPTIONS.get(tb_name, ""),
            tools=tuple(tools),
        )
        for tb_name, tools in anchor_tools_by_toolbox.items()
    )
    return Catalog(granularity=granularity_name, toolboxes=toolboxes)


narrow_rich_80_catalog = _build_huge(80, "narrow-rich-80")
narrow_rich_150_catalog = _build_huge(150, "narrow-rich-150")


def stats() -> str:
    """Diagnostic summary for both huge variants."""
    lines = []
    for c in (narrow_rich_catalog, narrow_rich_80_catalog, narrow_rich_150_catalog):
        by_box = {tb.name: len(tb.tools) for tb in c.toolboxes}
        n_tools = sum(by_box.values())
        text = sum(len(t.description) for t in c.all_tools)
        lines.append(f"  {c.granularity:<20s} n={n_tools:>4d}  text={text:>6d} chars  by_box={by_box}")
    return "\n".join(lines)
