"""Phase 3 v4: 2 failure modes × 3 conditions × N replicates.

Generalizes the prior phase 3 experiment:
  - Failure modes: 'verify' (pytest in non-standard dir) and 'runner'
    (project-specific ./tools/run command).
  - Promotion uses the LLM-based synthesizer (Sonnet) — proves the architecture
    works on arbitrary failure patterns, not just hand-coded ones.
  - Replicates measure noise; the 4×/3× claim should hold across runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
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


FAILURE_MODES = {
    "verify":  ["V1-verify-auth", "V2-verify-parser", "V3-verify-client", "V4-verify-config", "V5-verify-db"],
    "runner":  ["R1-run-build",   "R2-run-migrate",   "R3-run-seed",      "R4-run-lint",      "R5-run-deploy"],
}

CONDITIONS = ["baseline", "lessons-only", "promotion-llm"]


def _catalog_with_derived(base: Catalog, derived_tools: list) -> Catalog:
    if not derived_tools:
        return base
    new_boxes = []
    for tb in base.toolboxes:
        if tb.name == "filesystem":
            new_boxes.append(
                Toolbox(name=tb.name, description=tb.description,
                        tools=tuple(tb.tools) + tuple(d.tool for d in derived_tools))
            )
        else:
            new_boxes.append(tb)
    return Catalog(granularity=base.granularity, toolboxes=tuple(new_boxes))


def _make_source_tool_resolver(catalog: Catalog):
    by_name = {t.name: t for t in catalog.all_tools}
    return lambda name: by_name.get(name)


def run_replicate(
    mode: str,
    condition: str,
    rep_idx: int,
    fout,
    classifier_model: str = "claude-haiku-4-5",
    final_model: str = "claude-haiku-4-5",
    max_retries: int = 4,
) -> tuple[int, float, int]:
    """Run one (mode, condition, rep) tuple over a 5-task sequence.

    Returns (n_first_try_success, total_cost, n_promotions).
    """
    uses_lessons = "lessons" in condition or "promotion" in condition
    uses_promotion = "promotion" in condition

    state_dir = Path("data/lessons_phase3_v4") / mode / condition / f"rep{rep_idx}"
    state_dir.mkdir(parents=True, exist_ok=True)
    store = LessonStore(path=state_dir / "lessons.jsonl") if uses_lessons else None

    base_catalog = primitive_catalog
    if uses_promotion:
        pm = PromotionManager(
            threshold=1,
            synthesizer="llm",
            source_tool_resolver=_make_source_tool_resolver(base_catalog),
        )
    else:
        pm = None

    clear_derived_tools()

    approach = FullApproach()
    total_cost = 0.0
    first_try_success = 0
    n_promotions = 0
    sequence = FAILURE_MODES[mode]

    for ep_idx, task_id in enumerate(sequence, start=1):
        task = by_id(task_id)
        derived_for_this_ep = pm.derived_tools if pm else []
        catalog = _catalog_with_derived(base_catalog, derived_for_this_ep)

        if store is not None:
            phase = LessonAwareOnePhase(store, plan_first=True)
        else:
            phase = PlanFirstPhase()
        agent_step = make_agent_step(approach, phase, catalog, final_model)

        t0 = time.perf_counter()
        result = run_and_score(task, catalog, agent_step, final_model, max_retries=max_retries)
        wall_s = time.perf_counter() - t0
        ep = result.episode

        first_try = ep.n_attempts == 1 and result.task_success
        if first_try:
            first_try_success += 1

        # Classify failures + maybe promote
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
                                n_promotions += 1
                    except Exception as exc:  # noqa: BLE001
                        print(f"   classifier error: {exc}")

        synth_cost = pm.synth_cost_usd if pm else 0.0
        # Reset for next-episode delta calculation
        if pm is not None:
            pm.synth_cost_usd = 0.0

        episode_total = ep.total_cost_usd + classifier_cost + synth_cost
        total_cost += episode_total

        flag = "OK " if result.task_success else "FAIL"
        ft = "✓" if first_try else "✗"
        print(f"  rep{rep_idx} ep{ep_idx} [{flag}] ft={ft} {task_id[:25]:<25s} "
              f"att={ep.n_attempts} m={result.score.required_matched}/{result.score.required_total} "
              f"err={ep.error_categories_seen} promo={promotions} "
              f"$={episode_total:.4f} (synth=${synth_cost:.4f})")

        row = {
            "failure_mode": mode,
            "condition": condition,
            "replicate": rep_idx,
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
            "cost_synth_usd": synth_cost,
            "cost_total_usd": episode_total,
            "wall_s": wall_s,
            "new_lessons": new_lessons,
            "promotions": promotions,
            "derived_tools_now": [d.tool.name for d in (pm.derived_tools if pm else [])],
        }
        fout.write(json.dumps(row) + "\n")
        fout.flush()

    if store is not None:
        store.save()

    return first_try_success, total_cost, n_promotions


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/runs/phase3_v4.jsonl")
    ap.add_argument("--replicates", type=int, default=3)
    ap.add_argument("--max-cost-usd", type=float, default=10.0)
    ap.add_argument("--mode", action="append", help="Restrict to failure mode(s).")
    ap.add_argument("--condition", action="append", help="Restrict to condition(s).")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    modes = args.mode or list(FAILURE_MODES.keys())
    conditions = args.condition or CONDITIONS

    started = time.time()
    grand_cost = 0.0
    summary_rows: list[dict] = []

    print(f"Phase 3 v4: {len(modes)} modes × {len(conditions)} conds × {args.replicates} reps × 5 episodes\n")

    with out_path.open("a") as fout:
        for mode in modes:
            for cond in conditions:
                ft_total = 0
                cost_total = 0.0
                promo_total = 0
                print("=" * 96)
                print(f"MODE: {mode}  CONDITION: {cond}")
                print("=" * 96)
                for rep in range(args.replicates):
                    if grand_cost > args.max_cost_usd:
                        print(f"!! Budget cap ${args.max_cost_usd:.2f} hit")
                        break
                    ft, cost, promo = run_replicate(mode, cond, rep, fout)
                    ft_total += ft
                    cost_total += cost
                    promo_total += promo
                    grand_cost += cost
                n = len(FAILURE_MODES[mode]) * args.replicates
                summary_rows.append({
                    "mode": mode, "condition": cond,
                    "first_try": f"{ft_total}/{n}",
                    "first_try_pct": 100.0 * ft_total / n,
                    "cost": cost_total,
                    "promotions": promo_total,
                })
                print(f"\n  → mode={mode} cond={cond}: first_try={ft_total}/{n} cost=${cost_total:.4f} promotions={promo_total}\n")
                if grand_cost > args.max_cost_usd:
                    break
            if grand_cost > args.max_cost_usd:
                break

    elapsed = time.time() - started
    print("=" * 96)
    print(f"DONE in {elapsed:.0f}s, grand cost ${grand_cost:.4f}")
    for s in summary_rows:
        print(f"  {s['mode']:8s} {s['condition']:18s} first_try={s['first_try']:>6s} ({s['first_try_pct']:.0f}%)  $={s['cost']:.4f}  promo={s['promotions']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
