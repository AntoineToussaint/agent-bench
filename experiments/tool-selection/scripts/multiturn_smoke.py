"""Quick smoke test: run M2 with multi-turn Haiku 1phase. Should fail once,
recover, succeed."""

from __future__ import annotations

import os

from dotenv import load_dotenv

from tool_selection.approaches.full import FullApproach
from tool_selection.catalogs import narrow_rich_catalog
from tool_selection.execution.agent_steps import make_agent_step
from tool_selection.execution.episode_runner import run_and_score
from tool_selection.phases.one_phase import OnePhase
from tool_selection.tasks import by_id

load_dotenv()


def main() -> int:
    task = by_id("M2-branch-fix-pr")
    print(f"Task: {task.id} (triggers={len(task.failure_triggers)})")
    print(f"Required calls: {len(task.required_calls)}")
    print()

    approach = FullApproach()
    phase = OnePhase()
    agent_step = make_agent_step(approach, phase, narrow_rich_catalog, "claude-haiku-4-5")

    result = run_and_score(task, narrow_rich_catalog, agent_step, "claude-haiku-4-5", max_retries=4)
    episode = result.episode

    print(f"Task success:  {result.task_success}")
    print(f"  runtime ok:  {episode.succeeded}")
    print(f"  scorer:      {result.score.required_matched}/{result.score.required_total} required matched")
    print(f"Attempts:      {episode.n_attempts}")
    print(f"Errors seen:   {episode.error_categories_seen}")
    print(f"Cost:          ${episode.total_cost_usd:.4f}")
    print(f"Latency:       {episode.total_latency_ms:.0f}ms")
    print()

    for i, att in enumerate(episode.attempts, start=1):
        print(f"### Attempt {i}")
        for c, r in zip(att.calls, att.results):
            args_short = {k: v for k, v in c.args.items() if v is not None}
            args_repr = str(args_short)[:120]
            status = "ok" if r.ok else f"ERROR ({r.category})"
            print(f"  {c.tool}({args_repr}) → {status}")
            if not r.ok:
                print(f"      {r.error[:100]}")
        print()

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
