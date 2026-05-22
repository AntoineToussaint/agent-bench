"""Phase 3.5: add the description-augment condition.

4 conditions × 2 failure modes × N replicates × 5 episodes.

The 4 conditions:
  - baseline           — no lessons
  - lessons-only       — text lessons appended to user message each turn
  - promotion-llm      — recurring lessons synthesize a new derived tool (heavy)
  - description-augment — recurring lessons append an addendum to the source
                          tool's description (light; just better docs)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from tool_selection.approaches.full import FullApproach
from tool_selection.catalogs import primitive_catalog
from tool_selection.execution.agent_steps import make_agent_step
from tool_selection.execution.augmenter import AugmentationManager, apply_patches_to_tool
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

CONDITIONS = ["baseline", "lessons-only", "promotion-llm", "description-augment"]


def _build_catalog(base: Catalog, derived_tools: list, patches: dict) -> Catalog:
    """Build a fresh catalog including derived tools and patched descriptions."""
    new_boxes = []
    for tb in base.toolboxes:
        new_tools = []
        for t in tb.tools:
            patched = apply_patches_to_tool(t, patches.get(t.name, []))
            new_tools.append(patched)
        # Add any derived tools belonging to this toolbox
        for d in derived_tools:
            if d.tool.toolbox == tb.name:
                new_tools.append(d.tool)
        new_boxes.append(Toolbox(name=tb.name, description=tb.description, tools=tuple(new_tools)))
    return Catalog(granularity=base.granularity, toolboxes=tuple(new_boxes))


def _resolver(catalog: Catalog):
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
) -> tuple[int, float]:
    uses_lessons = condition in {"lessons-only", "promotion-llm", "description-augment"}
    uses_promo = condition == "promotion-llm"
    uses_augment = condition == "description-augment"

    state_dir = Path("data/lessons_phase35") / mode / condition / f"rep{rep_idx}"
    state_dir.mkdir(parents=True, exist_ok=True)
    store = LessonStore(path=state_dir / "lessons.jsonl") if uses_lessons else None

    base = primitive_catalog
    pm = PromotionManager(threshold=1, synthesizer="llm", source_tool_resolver=_resolver(base)) if uses_promo else None
    am = AugmentationManager(threshold=1, source_tool_resolver=_resolver(base)) if uses_augment else None

    clear_derived_tools()

    approach = FullApproach()
    total_cost = 0.0
    first_try_success = 0

    for ep_idx, task_id in enumerate(FAILURE_MODES[mode], start=1):
        task = by_id(task_id)

        derived_tools = pm.derived_tools if pm else []
        patches = am.patches if am else {}
        catalog = _build_catalog(base, derived_tools, patches)

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

        classifier_cost = 0.0
        events: list[str] = []  # promotions OR augmentations
        if uses_lessons:
            for att in ep.attempts:
                for call, res in zip(att.calls, att.results):
                    if res.ok:
                        continue
                    try:
                        lesson, telem = classify_failure(
                            task=task, call_tool=call.tool, call_args=call.args,
                            error_message=res.error, category=res.category,
                            model=classifier_model,
                        )
                        classifier_cost += (
                            telem["input_tokens"] * 1.0 / 1_000_000
                            + telem["output_tokens"] * 5.0 / 1_000_000
                        )
                        if store is not None:
                            store.add(lesson)
                        if pm is not None:
                            promoted = pm.add_lesson(lesson)
                            if promoted is not None:
                                register_derived_tool(promoted)
                                events.append(f"derived:{promoted.tool.name}")
                        if am is not None:
                            patch = am.add_lesson(lesson)
                            if patch is not None:
                                events.append(f"augment:{patch.target_tool}")
                    except Exception as exc:  # noqa: BLE001
                        print(f"   classifier error: {exc}")

        synth_cost = 0.0
        if pm is not None:
            synth_cost += pm.synth_cost_usd
            pm.synth_cost_usd = 0.0
        if am is not None:
            synth_cost += am.synth_cost_usd
            am.synth_cost_usd = 0.0

        ep_total = ep.total_cost_usd + classifier_cost + synth_cost
        total_cost += ep_total

        flag = "OK " if result.task_success else "FAIL"
        ft = "✓" if first_try else "✗"
        print(f"  rep{rep_idx} ep{ep_idx} [{flag}] ft={ft} {task_id[:24]:<24s} "
              f"att={ep.n_attempts} m={result.score.required_matched}/{result.score.required_total} "
              f"events={events} $={ep_total:.4f}")

        row = {
            "failure_mode": mode, "condition": condition, "replicate": rep_idx,
            "episode_index": ep_idx, "task_id": task_id,
            "task_success": result.task_success, "first_try_success": first_try,
            "n_attempts": ep.n_attempts,
            "required_matched": result.score.required_matched,
            "required_total": result.score.required_total,
            "error_categories_seen": ep.error_categories_seen,
            "cost_episode_usd": ep.total_cost_usd,
            "cost_classifier_usd": classifier_cost,
            "cost_synth_usd": synth_cost,
            "cost_total_usd": ep_total,
            "wall_s": wall_s,
            "events": events,
        }
        fout.write(json.dumps(row) + "\n")
        fout.flush()

    if store is not None:
        store.save()

    return first_try_success, total_cost


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/runs/phase35.jsonl")
    ap.add_argument("--replicates", type=int, default=3)
    ap.add_argument("--max-cost-usd", type=float, default=10.0)
    ap.add_argument("--mode", action="append")
    ap.add_argument("--condition", action="append")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    modes = args.mode or list(FAILURE_MODES.keys())
    conditions = args.condition or CONDITIONS

    started = time.time()
    grand_cost = 0.0
    summary: list[dict] = []
    print(f"Phase 3.5: {len(modes)} modes × {len(conditions)} conds × {args.replicates} reps × 5 eps\n")

    with out_path.open("a") as fout:
        for mode in modes:
            for cond in conditions:
                ft_total = 0
                cost_total = 0.0
                print("=" * 96)
                print(f"MODE: {mode}  CONDITION: {cond}")
                print("=" * 96)
                for rep in range(args.replicates):
                    if grand_cost > args.max_cost_usd:
                        print(f"!! Budget cap ${args.max_cost_usd:.2f} hit"); break
                    ft, cost = run_replicate(mode, cond, rep, fout)
                    ft_total += ft; cost_total += cost; grand_cost += cost
                n = len(FAILURE_MODES[mode]) * args.replicates
                summary.append({"mode": mode, "cond": cond, "ft": f"{ft_total}/{n}",
                                "pct": 100.0 * ft_total / n, "cost": cost_total})
                print(f"\n  → {mode}/{cond}: {ft_total}/{n} ({100*ft_total/n:.0f}%) cost=${cost_total:.4f}\n")
                if grand_cost > args.max_cost_usd: break
            if grand_cost > args.max_cost_usd: break

    print("=" * 96)
    print(f"DONE in {time.time()-started:.0f}s, grand cost ${grand_cost:.4f}\n")
    for s in summary:
        print(f"  {s['mode']:8s} {s['cond']:22s} ft={s['ft']:>6s} ({s['pct']:.0f}%)  $={s['cost']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
