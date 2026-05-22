"""Thesis-oriented analysis of the sweep results.

Reads data/runs/sweep_v2_*.jsonl and produces:
  - Per-(strategy, phase, granularity, model) success / cost / latency / decomposed metrics
  - Pareto frontier (cost × success) per model
  - Failure-mode breakdown by task family (each task tags a research-flagged
    failure mode in its note)
  - The headline verdict: best strategy per (model × granularity) by success
    first, cost tiebreaker, plus the cost-per-success metric.

Usage:
    uv run python scripts/thesis.py
    uv run python scripts/thesis.py --glob 'data/runs/sweep_v2_*.jsonl'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

# Maps task IDs to research-grounded failure-mode tags. Tasks not listed are
# treated as "general" (no specific failure-mode hypothesis).
TASK_FAILURE_MODE: dict[str, str] = {
    "E1-stage-and-commit-typo": "general",
    "E2-draft-pr": "schema-optional-args",
    "E3-read-range": "schema-optional-args",
    "E4-pr-conversation-comment": "confusable-sibling",
    "E5-phantom-tool-rebase": "phantom-tool",
    "M1-version-bump-release": "long-sequence",
    "M2-branch-fix-pr": "long-sequence",
    "M3-inline-review-comment": "confusable-sibling",
    "M4-rename-and-commit": "general",
    "M5-argument-coupling": "argument-coupling",
    "M6-wrong-order-temptation": "wrong-order-temptation",
    "M7-state-confusion-mkdir": "state-confusion",
    "M8-parallel-similar-batched-commit": "parallel-similar",
    "H1-feature-branch-full-flow": "long-sequence",
    "H2-pr-multi-inline-review": "confusable-sibling",
    "H3-hotfix-with-cross-step-coupling": "argument-coupling",
}


def _wall_clock_latency_ms(row: dict) -> float:
    """Correct wall-clock latency. For two-phase rows the pipeline shape is
    [select, arg, arg, ...] and the arg calls run in parallel, so wall-clock
    is select.latency + max(arg.latency), not sum(...). For all other phases
    the sum-of-step latencies IS wall-clock."""
    pipeline = row.get("pipeline", []) or []
    phase = row.get("phase", "")
    if not pipeline:
        return float(row.get("total_latency_ms", 0.0))
    # If any step has parallel_group set, aggregate accordingly (new format).
    if any(s.get("parallel_group") is not None for s in pipeline):
        sequential = sum(s["latency_ms"] for s in pipeline if s.get("parallel_group") is None)
        groups: dict[int, list[float]] = {}
        for s in pipeline:
            g = s.get("parallel_group")
            if g is not None:
                groups.setdefault(g, []).append(s["latency_ms"])
        return sequential + sum(max(v) for v in groups.values())
    # Otherwise: legacy data. For 2phase variants, assume pipeline[0] is the
    # selection step (sequential) and pipeline[1:] are parallel arg calls.
    if phase.startswith("2phase") and len(pipeline) >= 2:
        return pipeline[0]["latency_ms"] + max(s["latency_ms"] for s in pipeline[1:])
    return sum(s["latency_ms"] for s in pipeline)


def load(glob: str) -> pl.DataFrame:
    paths = sorted(Path().glob(glob))
    if not paths:
        raise FileNotFoundError(f"No files match {glob}")
    df = pl.concat([pl.read_ndjson(p) for p in paths])
    print(f"Loaded {df.height} runs from {len(paths)} file(s): {[p.name for p in paths]}")
    # Recompute wall-clock latency to fix legacy 2phase rows that summed parallel calls.
    new_lat = []
    for r in df.iter_rows(named=True):
        new_lat.append(_wall_clock_latency_ms(r))
    fm_series = df["task_id"].map_elements(
        lambda x: TASK_FAILURE_MODE.get(x, "uncategorized"), return_dtype=pl.Utf8
    )
    df = df.with_columns(
        fm_series.alias("failure_mode"),
        pl.Series(name="wall_latency_ms", values=new_lat),
    )
    return df


def headline_table(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.group_by(["strategy", "phase", "granularity", "model"])
        .agg(
            n=pl.len(),
            success=pl.col("success").cast(pl.Float64).mean(),
            sel_acc=pl.col("selection_accuracy").mean(),
            args_acc=pl.col("args_accuracy_given_selection").mean(),
            cost=pl.col("total_cost_usd").mean(),
            wall_latency_s=(pl.col("wall_latency_ms") / 1000).mean(),
            seq_latency_s=(pl.col("total_latency_ms") / 1000).mean(),
            hall_rate=pl.col("hallucinated").list.len().cast(pl.Float64).mean(),
            forb_rate=pl.col("forbidden_called").list.len().cast(pl.Float64).mean(),
        )
        .with_columns(
            cost_per_success=pl.when(pl.col("success") > 0)
            .then(pl.col("cost") / pl.col("success"))
            .otherwise(None)
        )
        .sort(["model", "granularity", "success", "cost"], descending=[False, False, True, False])
    )


def pareto_frontier(df: pl.DataFrame) -> pl.DataFrame:
    """For each (model, granularity), keep only Pareto-non-dominated points
    in (cost, success) space — i.e. cheaper or higher success than every
    other point."""
    agg = (
        df.group_by(["strategy", "phase", "granularity", "model"])
        .agg(
            success=pl.col("success").cast(pl.Float64).mean(),
            cost=pl.col("total_cost_usd").mean(),
            latency_s=(pl.col("wall_latency_ms") / 1000).mean(),
        )
        .sort(["model", "granularity", "cost"])
    )
    pareto_rows = []
    for (mdl, gran), group in agg.group_by(["model", "granularity"]):
        best_so_far = -1.0
        for r in group.iter_rows(named=True):
            if r["success"] > best_so_far:
                pareto_rows.append({**r, "pareto": True})
                best_so_far = r["success"]
    if not pareto_rows:
        return pl.DataFrame()
    return pl.from_dicts(pareto_rows).sort(["model", "granularity", "cost"])


def failure_mode_breakdown(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.group_by(["failure_mode", "phase", "model"])
        .agg(
            n=pl.len(),
            success=pl.col("success").cast(pl.Float64).mean(),
            sel_acc=pl.col("selection_accuracy").mean(),
            args_acc=pl.col("args_accuracy_given_selection").mean(),
        )
        .sort(["failure_mode", "model", "phase"])
    )


def phase_uplift(df: pl.DataFrame) -> pl.DataFrame:
    """For each (strategy, granularity, model) cell, the difference in success
    between 1phase-plan and 1phase. Quantifies the plan-first uplift."""
    pivot = (
        df.group_by(["strategy", "granularity", "model", "phase"])
        .agg(success=pl.col("success").cast(pl.Float64).mean(),
             cost=pl.col("total_cost_usd").mean())
        .pivot(values=["success", "cost"], index=["strategy", "granularity", "model"], on="phase")
    )
    out = pivot
    if "success_1phase-plan" in pivot.columns and "success_1phase" in pivot.columns:
        out = out.with_columns(
            plan_uplift_pp=100 * (pl.col("success_1phase-plan") - pl.col("success_1phase")),
            plan_cost_delta=pl.col("cost_1phase-plan") - pl.col("cost_1phase"),
        ).sort("plan_uplift_pp", descending=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="data/runs/sweep_v2_*.jsonl")
    args = ap.parse_args()

    try:
        df = load(args.glob)
    except FileNotFoundError as e:
        print(e)
        return 1

    print(f"\nUnique conditions:")
    print(f"  strategies:    {sorted(df['strategy'].unique().to_list())}")
    print(f"  phases:        {sorted(df['phase'].unique().to_list())}")
    print(f"  granularities: {sorted(df['granularity'].unique().to_list())}")
    print(f"  models:        {sorted(df['model'].unique().to_list())}")
    print(f"  tasks:         {df['task_id'].n_unique()}")
    print(f"  failure modes: {sorted(df['failure_mode'].unique().to_list())}")

    print("\n\n=== Headline table — sorted by success then cost, per (model, granularity) ===\n")
    h = headline_table(df)
    print(h.with_columns(
        success=(pl.col("success") * 100).round(0),
        sel_acc=(pl.col("sel_acc") * 100).round(0),
        args_acc=(pl.col("args_acc") * 100).round(0),
        cost=pl.col("cost").round(4),
        wall_latency_s=pl.col("wall_latency_s").round(2),
        seq_latency_s=pl.col("seq_latency_s").round(2),
        cost_per_success=pl.col("cost_per_success").round(4),
    ))

    print("\n\n=== Pareto frontier (cost × success), per (model × granularity) ===\n")
    pf = pareto_frontier(df)
    print(pf.with_columns(
        success=(pl.col("success") * 100).round(0),
        cost=pl.col("cost").round(4),
        latency_s=pl.col("latency_s").round(2),
    ))

    print("\n\n=== Plan-first uplift (success_1phase-plan - success_1phase) ===\n")
    pu = phase_uplift(df)
    print(pu)

    print("\n\n=== Failure-mode breakdown (success per failure mode × phase × model) ===\n")
    fm = failure_mode_breakdown(df)
    print(fm.with_columns(
        success=(pl.col("success") * 100).round(0),
        sel_acc=(pl.col("sel_acc") * 100).round(0),
        args_acc=(pl.col("args_acc") * 100).round(0),
    ))

    print("\n\n=== Verdict: best (strategy, phase) per (model, granularity) ===\n")
    for (mdl, gran), group in headline_table(df).group_by(["model", "granularity"]):
        top = group.head(1).row(0, named=True)
        print(
            f"  {mdl}/{gran}: {top['strategy']}+{top['phase']} "
            f"→ {100*top['success']:.0f}% success @ ${top['cost']:.4f}/q, "
            f"cost-per-success ${top['cost_per_success']:.4f}, wall_lat={top['wall_latency_s']:.1f}s "
            f"(seq={top['seq_latency_s']:.1f}s)"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
