"""Run the full strategy sweep and save per-condition JSONL traces.

A 'condition' is (strategy × granularity × final_shot_model). For each condition
we run all tasks and emit one JSONL row per task into data/runs/sweep.jsonl
(append-friendly — re-runs overwrite by default).

Use --quick to limit to a representative subset (saves API spend).
Use --strategy / --task to scope further.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from tool_selection.catalogs import CATALOGS
from tool_selection.phases import PHASES
from tool_selection.runner import run_one
from tool_selection.strategies import DEFAULT_SWEEP, build_strategy
from tool_selection.tasks import ALL_TASKS

load_dotenv()

DEFAULT_GRANULARITIES = ("narrow", "fat")
DEFAULT_MODELS = ("claude-haiku-4-5",)

QUICK_STRATEGIES = (
    "full",
    "toolbox:bm25",
    "toolbox:llm-haiku",
    "tool:bm25",
    "tool:embed-openai-small",
    "hybrid:embed-openai-small+llm-haiku",
    "cascade:llm-haiku+bm25",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="Run a smaller strategy subset")
    ap.add_argument("--strategy", action="append", help="Restrict to this strategy id (repeatable)")
    ap.add_argument("--task", action="append", help="Restrict to this task id (repeatable)")
    ap.add_argument("--granularity", action="append", help="Catalog granularity: narrow / fat / narrow-rich. Repeatable.")
    ap.add_argument("--model", action="append", help="Final-shot model (repeatable)")
    ap.add_argument("--phase", action="append", help=f"Final-shot phase (repeatable). Options: {sorted(PHASES)}. Default: 1phase only.")
    ap.add_argument("--out", default="data/runs/sweep.jsonl")
    ap.add_argument("--max-cost-usd", type=float, default=5.0)
    args = ap.parse_args()

    strategies = tuple(args.strategy) if args.strategy else (
        QUICK_STRATEGIES if args.quick else DEFAULT_SWEEP
    )
    granularities = tuple(args.granularity) if args.granularity else DEFAULT_GRANULARITIES
    models = tuple(args.model) if args.model else DEFAULT_MODELS
    phase_ids = tuple(args.phase) if args.phase else ("1phase",)
    for pid in phase_ids:
        if pid not in PHASES:
            print(f"unknown phase: {pid!r}. options: {sorted(PHASES)}")
            return 2
    tasks = [t for t in ALL_TASKS if (not args.task or t.id in args.task)]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()  # fresh sweep

    total_runs_planned = len(strategies) * len(granularities) * len(models) * len(phase_ids) * len(tasks)
    print(f"Sweep: {len(strategies)} strategies × {len(granularities)} granularities × "
          f"{len(models)} models × {len(phase_ids)} phases × {len(tasks)} tasks "
          f"= {total_runs_planned} runs")
    print(f"Phases: {list(phase_ids)}")
    print(f"Budget: ${args.max_cost_usd:.2f}")
    print(f"Out: {out}")
    print("-" * 96)

    total_cost = 0.0
    total_runs = 0
    successes = 0
    started = time.time()

    with out.open("a") as f:
        for granularity in granularities:
            catalog = CATALOGS[granularity]
            for model in models:
                for strategy_id in strategies:
                    try:
                        approach = build_strategy(strategy_id)
                    except Exception as e:
                        print(f"  SKIP {strategy_id}: {e}")
                        continue
                    for phase_id in phase_ids:
                        phase = PHASES[phase_id]()
                        print(f"\n=== granularity={granularity} model={model} strategy={strategy_id} phase={phase_id} ===")
                        for task in tasks:
                            if total_cost > args.max_cost_usd:
                                print(f"\n!! Budget cap ${args.max_cost_usd:.2f} hit. Stopping.")
                                print(f"Spent ${total_cost:.4f} on {total_runs} runs ({successes}/{total_runs} succ).")
                                return 0
                            trace, sc = run_one(approach, catalog, model, task, phase=phase)
                            total_cost += trace.total_cost_usd
                            total_runs += 1
                            if sc.task_success:
                                successes += 1
                            flag = "OK " if sc.task_success else "FAIL"
                            n_surfaced = len(trace.surfaced_tools)
                            n_calls = len(trace.final_calls)
                            print(
                                f"  [{flag}] {task.id:38s} surf={n_surfaced:>3d} calls={n_calls:>2d} "
                                f"matched={sc.required_matched:>2d}/{sc.required_total:<2d} "
                                f"sel={sc.selection_matched:>2d}/{sc.required_total:<2d} "
                                f"cost=${trace.total_cost_usd:.4f} lat={trace.total_latency_ms:>5.0f}ms"
                            )
                            row = {
                                "strategy": strategy_id,
                                "phase": phase_id,
                                "granularity": granularity,
                                "model": model,
                                "task_id": task.id,
                                "task_difficulty": task.difficulty,
                                "success": sc.task_success,
                                "required_total": sc.required_total,
                                "required_matched": sc.required_matched,
                                "selection_matched": sc.selection_matched,
                                "selection_accuracy": sc.selection_accuracy,
                                "args_accuracy_given_selection": sc.args_accuracy_given_selection,
                                "missing": sc.missing_required,
                                "hallucinated": sc.hallucinated_calls,
                                "extras": sc.extra_calls,
                                "forbidden_called": sc.forbidden_called,
                                "schema_invalid": sc.schema_invalid_calls,
                                "total_cost_usd": trace.total_cost_usd,
                                "total_latency_ms": trace.total_latency_ms,
                                "input_tokens": trace.total_input_tokens,
                                "output_tokens": trace.total_output_tokens,
                                "surfaced_count": len(trace.surfaced_tools),
                                "n_calls": len(trace.final_calls),
                                "pipeline": [asdict(s) for s in trace.pipeline],
                                "final_calls": trace.final_calls,
                                "surfaced_tools": trace.surfaced_tools,
                                "error": trace.error,
                            }
                            f.write(json.dumps(row) + "\n")
                            f.flush()

    elapsed = time.time() - started
    print("\n" + "=" * 96)
    print(f"DONE: {total_runs} runs, {successes}/{total_runs} succ ({100*successes/max(1,total_runs):.0f}%), "
          f"total cost ${total_cost:.4f}, {elapsed:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
