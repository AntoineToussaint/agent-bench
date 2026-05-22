"""Phase 3 experiment: lessons-only vs lessons+promotion.

Episode sequence: V1-V5, all sharing the same failure mode ('pytest path
should use verify/ not tests/ or bare filename'). The model has no
training prior for this project-specific convention.

Conditions:
  1. baseline                — no lessons; each episode pays the failure tax
  2. lessons-only            — text-level lessons accumulate; after lesson is
                               injected the model should succeed first-try
  3. lessons-plus-promotion  — after N=2 lessons of the same cluster, promote
                               to a derived `pytest_run(test_path)` tool that
                               structurally encodes the fix. Subsequent
                               episodes use it; the lesson burden retires.

Measures per episode: first-try success, total attempts, error categories,
cost. Hypothesis: condition 3 dominates 2 on cost-per-success at later
episodes (the promoted tool drops the lesson context burden and structurally
eliminates the failure mode).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv

from tool_selection.approaches.full import FullApproach
from tool_selection.catalogs import primitive_catalog
from tool_selection.execution.agent_steps import make_agent_step
from tool_selection.execution.classifier import classify_failure
from tool_selection.execution.episode_runner import run_and_score
from tool_selection.execution.executor import clear_derived_tools, register_derived_tool
from tool_selection.execution.lessons import LessonStore
from tool_selection.execution.promotion import PromotionManager
from tool_selection.phases.lesson_aware import LessonAwareOnePhase
from tool_selection.phases.one_phase import PlanFirstPhase
from tool_selection.tasks import by_id
from tool_selection.types import Catalog, Toolbox

load_dotenv()


EPISODE_SEQUENCE = [
    "V1-verify-auth",
    "V2-verify-parser",
    "V3-verify-client",
    "V4-verify-config",
    "V5-verify-db",
]


def _catalog_with_derived(base: Catalog, derived_tools: list) -> Catalog:
    """Build a fresh catalog including any promoted derived tools."""
    if not derived_tools:
        return base
    new_boxes = []
    for tb in base.toolboxes:
        if tb.name == "filesystem":
            new_boxes.append(
                Toolbox(
                    name=tb.name,
                    description=tb.description,
                    tools=tuple(tb.tools) + tuple(d.tool for d in derived_tools),
                )
            )
        else:
            new_boxes.append(tb)
    return Catalog(granularity=base.granularity, toolboxes=tuple(new_boxes))


def run_condition(
    condition_name: str,
    fout,
    max_retries: int = 4,
    classifier_model: str = "claude-haiku-4-5",
    final_model: str = "claude-haiku-4-5",
) -> tuple[int, float]:
    """Run the V1-V5 sequence under one experimental condition.

    Returns (n_first_try_success, total_cost_usd).
    """
    uses_lessons = "lessons" in condition_name
    uses_promotion = "promotion" in condition_name

    # Per-condition state
    lessons_dir = Path("data/lessons_phase3") / condition_name
    lessons_dir.mkdir(parents=True, exist_ok=True)
    store = LessonStore(path=lessons_dir / "lessons.jsonl") if uses_lessons else None
    pm = PromotionManager(threshold=1) if uses_promotion else None

    # Each condition starts fresh — clear any derived tools from prior condition
    clear_derived_tools()

    approach = FullApproach()
    base_catalog = primitive_catalog
    total_cost = 0.0
    first_try_success = 0

    for ep_idx, task_id in enumerate(EPISODE_SEQUENCE, start=1):
        task = by_id(task_id)

        # Build catalog including any currently-promoted derived tools
        derived_for_this_ep = pm.derived_tools if pm else []
        catalog = _catalog_with_derived(base_catalog, derived_for_this_ep)

        # Pick the phase: lessons-aware if we have a store, else plain plan-first
        if store is not None:
            phase = LessonAwareOnePhase(store, plan_first=True)
        else:
            phase = PlanFirstPhase()

        agent_step = make_agent_step(approach, phase, catalog, final_model)

        t0 = time.perf_counter()
        result = run_and_score(task, catalog, agent_step, final_model, max_retries=max_retries)
        wall_s = time.perf_counter() - t0

        # First-try success = task succeeded on attempt 1 (no retries needed)
        ep = result.episode
        first_try = ep.n_attempts == 1 and result.task_success
        if first_try:
            first_try_success += 1

        # Process failures: classify and add lessons; promote if threshold hit
        classifier_cost = 0.0
        new_lessons = 0
        promotions: list[str] = []
        if uses_lessons:
            for att in ep.attempts:
                for call, res in zip(att.calls, att.results):
                    if res.ok:
                        continue
                    try:
                        lesson, telem = classify_failure(
                            task=task,
                            call_tool=call.tool,
                            call_args=call.args,
                            error_message=res.error,
                            category=res.category,
                            model=classifier_model,
                        )
                        classifier_cost += (
                            telem["input_tokens"] * 1.0 / 1_000_000
                            + telem["output_tokens"] * 5.0 / 1_000_000
                        )
                        if store is not None:
                            store.add(lesson)
                            new_lessons += 1
                        if pm is not None:
                            promoted = pm.add_lesson(lesson)
                            if promoted is not None:
                                register_derived_tool(promoted)
                                promotions.append(promoted.tool.name)
                    except Exception as exc:  # noqa: BLE001
                        print(f"   classifier error: {exc}")

        episode_total_cost = ep.total_cost_usd + classifier_cost
        total_cost += episode_total_cost

        flag = "OK " if result.task_success else "FAIL"
        ft_flag = "✓" if first_try else "✗"
        print(
            f"  ep{ep_idx} [{flag}] first_try={ft_flag} {task_id[:30]:<30s} "
            f"attempts={ep.n_attempts} matched={result.score.required_matched}/{result.score.required_total} "
            f"errors={ep.error_categories_seen} new_lessons={new_lessons} "
            f"promoted={promotions} cost=${episode_total_cost:.4f} wall={wall_s:.1f}s"
        )

        # Persist a JSONL row
        row = {
            "condition": condition_name,
            "episode_index": ep_idx,
            "task_id": task_id,
            "task_success": result.task_success,
            "first_try_success": first_try,
            "n_attempts": ep.n_attempts,
            "required_matched": result.score.required_matched,
            "required_total": result.score.required_total,
            "error_categories_seen": ep.error_categories_seen,
            "cost_episode_usd": ep.total_cost_usd,
            "cost_classifier_usd": classifier_cost,
            "cost_total_usd": episode_total_cost,
            "wall_s": wall_s,
            "new_lessons_added": new_lessons,
            "promotions_this_episode": promotions,
            "derived_tools_available_now": [d.tool.name for d in (pm.derived_tools if pm else [])],
            "attempts": [
                {
                    "calls": [
                        {"tool": c.tool, "args": c.args, "ok": r.ok,
                         "category": r.category, "error": r.error[:200]}
                        for c, r in zip(att.calls, att.results)
                    ],
                }
                for att in ep.attempts
            ],
        }
        fout.write(json.dumps(row) + "\n")
        fout.flush()

    if store is not None:
        store.save()

    return first_try_success, total_cost


CONDITIONS = ["baseline", "lessons-only", "lessons-plus-promotion"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/runs/phase3_experiment.jsonl")
    ap.add_argument("--max-cost-usd", type=float, default=4.0)
    ap.add_argument("--condition", action="append")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    conditions = args.condition or CONDITIONS

    started = time.time()
    print(f"Phase 3 experiment: {len(conditions)} conditions × {len(EPISODE_SEQUENCE)} episodes\n")

    summary: list[dict] = []
    with out_path.open("a") as fout:
        for cond in conditions:
            print("=" * 96)
            print(f"CONDITION: {cond}")
            print("=" * 96)
            n_first, cost = run_condition(cond, fout)
            summary.append({"condition": cond, "first_try": f"{n_first}/{len(EPISODE_SEQUENCE)}", "cost": cost})
            print(f"\n  → first-try success: {n_first}/{len(EPISODE_SEQUENCE)}, cost ${cost:.4f}\n")

    elapsed = time.time() - started
    print("=" * 96)
    print(f"DONE in {elapsed:.0f}s")
    for s in summary:
        print(f"  {s['condition']:<30s} first_try={s['first_try']}  cost=${s['cost']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
