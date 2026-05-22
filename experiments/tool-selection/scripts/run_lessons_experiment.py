"""Run the 4-condition lesson-learning experiment.

For each condition:
  1. Reset a fresh LessonStore (empty for baselines; populated across episodes for lesson conditions).
  2. Run an ordered sequence of tasks as multi-turn episodes.
  3. After failures within an episode, call the classifier to distill a Lesson and add it to the store.
  4. Record per-episode results (success, attempts, error categories, cost).

The sequence is designed so failure modes RECUR across tasks (M2/H1/H3 share
push-without-upstream + PR-before-push; M3/H2 share event-enum). Lesson
transfer manifests as: failures fired on early tasks but not on later ones.

Conditions:
  1. 1phase + Haiku, no lessons (baseline)
  2. 1phase + Haiku, with lessons (in-context augmentation)
  3. 2phase mixed (Haiku→Sonnet), no lessons
  4. 2phase mixed (Haiku→Sonnet), with lessons (phase-partitioned)

Hypothesis: lesson uplift in condition (4 - 3) > lesson uplift in (2 - 1).
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
from tool_selection.catalogs import CATALOGS
from tool_selection.execution.agent_steps import make_agent_step
from tool_selection.execution.classifier import classify_failure
from tool_selection.execution.episode_runner import run_and_score
from tool_selection.execution.lessons import LessonStore
from tool_selection.phases.lesson_aware import LessonAwareOnePhase, LessonAwareTwoPhase
from tool_selection.phases.one_phase import OnePhase, PlanFirstPhase
from tool_selection.phases.two_phase import TwoPhase
from tool_selection.tasks import by_id

load_dotenv()


# ---------- episode sequence ----------

# Episode sequence: all four pytest tasks (T1-T4) share the SAME failure mode
# — calling run_tests with a bare filename instead of a 'tests/'-prefixed path.
# This is the canonical real-world engineering failure ('run pytest in the wrong
# place') the user has seen repeatedly.
#
# If lessons work, the agent fails T1 (no prior lesson), generates a lesson
# ('prefix test paths with tests/'), then succeeds first-try on T2/T3/T4. The
# baseline conditions fail T1-T4 the same way every time (no learning).
#
# Difficulty intentionally varies the path *shape* (single file, directory,
# node-id) so the lesson has to generalize beyond the literal first failure.
EPISODE_SEQUENCE = [
    "BT1-bash-run-auth-tests",
    "BT2-bash-run-parser-tests",
    "BT3-bash-run-integration",
    "BT4-bash-run-single",
]


def _build_condition(name: str, store: LessonStore | None):
    """Returns (phase, model) for the condition.

    1phase conditions use plan-first because vanilla Haiku's one-shot ceiling
    hides runtime errors (model gives up before triggers can fire), making
    the lesson signal unreadable. Plan-first is the proper apples-to-apples
    baseline for measuring lesson uplift.
    """
    if name == "1phase-baseline":
        return PlanFirstPhase(), "claude-haiku-4-5"
    if name == "1phase-lessons":
        assert store is not None
        return LessonAwareOnePhase(store, plan_first=True), "claude-haiku-4-5"
    if name == "2phase-mixed-baseline":
        return TwoPhase(selection_model="claude-haiku-4-5", args_model="claude-sonnet-4-6"), "claude-haiku-4-5"
    if name == "2phase-mixed-lessons":
        assert store is not None
        return LessonAwareTwoPhase(store, selection_model="claude-haiku-4-5", args_model="claude-sonnet-4-6"), "claude-haiku-4-5"
    raise ValueError(name)


CONDITIONS = [
    "1phase-baseline",        # plan-first Haiku, no lessons
    "1phase-lessons",         # plan-first Haiku + lesson augmentation
    "2phase-mixed-baseline",  # Haiku→Sonnet two-phase, no lessons
    "2phase-mixed-lessons",   # Haiku→Sonnet two-phase + phase-partitioned lessons
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/runs/lessons_experiment.jsonl")
    ap.add_argument("--lessons-dir", default="data/lessons")
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--max-cost-usd", type=float, default=12.0)
    ap.add_argument("--condition", action="append", help="Restrict to specific condition(s).")
    ap.add_argument("--catalog", default="narrow-rich", choices=list(CATALOGS.keys()),
                    help="Catalog to use (narrow / narrow-rich / etc.). 'narrow' = thin descriptions.")
    args = ap.parse_args()
    catalog = CATALOGS[args.catalog]
    print(f"Using catalog: {args.catalog}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    lessons_dir = Path(args.lessons_dir)
    lessons_dir.mkdir(parents=True, exist_ok=True)

    approach = FullApproach()
    total_cost = 0.0
    total_runs = 0
    successes = 0
    started = time.time()

    conditions = args.condition or CONDITIONS

    with out_path.open("a") as fout:
        for cond in conditions:
            print(f"\n{'='*96}\n CONDITION: {cond}\n{'='*96}")
            # Fresh lesson store per condition (no leakage between conditions)
            uses_lessons = "lessons" in cond
            store = LessonStore.load(lessons_dir / f"{cond}.jsonl") if uses_lessons else None
            if store is not None:
                store.lessons.clear()  # start each condition fresh

            for ep_idx, task_id in enumerate(EPISODE_SEQUENCE, start=1):
                if total_cost > args.max_cost_usd:
                    print(f"\n!! Budget cap ${args.max_cost_usd:.2f} hit. Stopping.")
                    break

                task = by_id(task_id)
                phase, model = _build_condition(cond, store)
                agent_step = make_agent_step(approach, phase, catalog, model)

                t0 = time.perf_counter()
                result = run_and_score(task, catalog, agent_step, model, max_retries=args.max_retries)
                wall_s = time.perf_counter() - t0
                ep = result.episode

                # Classify failures from this episode and add to store
                classifier_cost = 0.0
                new_lessons = 0
                if uses_lessons and store is not None:
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
                                )
                                # Rough classifier cost (Haiku pricing)
                                classifier_cost += (
                                    telem["input_tokens"] * 1.0 / 1_000_000
                                    + telem["output_tokens"] * 5.0 / 1_000_000
                                )
                                store.add(lesson)
                                new_lessons += 1
                            except Exception as exc:  # noqa: BLE001
                                print(f"   classifier error: {exc}")

                episode_total_cost = ep.total_cost_usd + classifier_cost
                total_cost += episode_total_cost
                total_runs += 1
                if result.task_success:
                    successes += 1

                flag = "OK " if result.task_success else "FAIL"
                print(
                    f"  ep{ep_idx} [{flag}] {task_id[:38]:<38s} "
                    f"attempts={ep.n_attempts} matched={result.score.required_matched}/{result.score.required_total} "
                    f"errors={ep.error_categories_seen} new_lessons={new_lessons} "
                    f"cost=${episode_total_cost:.4f} wall={wall_s:.1f}s"
                )

                row = {
                    "condition": cond,
                    "episode_index": ep_idx,
                    "task_id": task_id,
                    "task_success": result.task_success,
                    "runtime_ok": ep.succeeded,
                    "n_attempts": ep.n_attempts,
                    "required_matched": result.score.required_matched,
                    "required_total": result.score.required_total,
                    "selection_matched": result.score.selection_matched,
                    "error_categories_seen": ep.error_categories_seen,
                    "n_calls_total": len(ep.flat_calls),
                    "cost_episode_usd": ep.total_cost_usd,
                    "cost_classifier_usd": classifier_cost,
                    "cost_total_usd": episode_total_cost,
                    "wall_s": wall_s,
                    "input_tokens": ep.total_input_tokens,
                    "output_tokens": ep.total_output_tokens,
                    "lessons_in_store_after": len(store) if store else 0,
                    "new_lessons_added": new_lessons,
                    "attempts": [
                        {
                            "calls": [
                                {"tool": c.tool, "args": c.args, "result_ok": r.ok,
                                 "result_category": r.category, "result_error": r.error[:200]}
                                for c, r in zip(att.calls, att.results)
                            ],
                        }
                        for att in ep.attempts
                    ],
                }
                fout.write(json.dumps(row) + "\n")
                fout.flush()

            # Persist final lesson store for this condition
            if store is not None:
                store.save()
                print(f"\n  Lessons saved to {store.path} (n={len(store)})")

    elapsed = time.time() - started
    print(f"\n{'='*96}")
    print(f"DONE: {total_runs} episodes, {successes}/{total_runs} task_success ({100*successes/max(1,total_runs):.0f}%)")
    print(f"Total cost ${total_cost:.4f}, {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
