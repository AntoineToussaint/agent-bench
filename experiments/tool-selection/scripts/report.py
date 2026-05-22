"""Plain-text sweep report: per-strategy success / cost / latency / failure breakdown.

Reads data/runs/sweep_*.jsonl (concat) and prints a sorted verdict table.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="data/runs/sweep_*.jsonl")
    ap.add_argument("--by", choices=["strategy", "strategy_x_granularity", "task"], default="strategy_x_granularity")
    args = ap.parse_args()

    paths = sorted(Path().glob(args.glob))
    if not paths:
        print(f"No files match {args.glob}")
        return 1
    df = pl.concat([pl.read_ndjson(p) for p in paths])
    print(f"Loaded {df.height} runs from {len(paths)} file(s)")
    print(f"  strategies: {df['strategy'].n_unique()}, granularities: {sorted(df['granularity'].unique().to_list())}, models: {sorted(df['model'].unique().to_list())}")
    print(f"  tasks: {df['task_id'].n_unique()}")
    print()

    group_cols = {
        "strategy": ["strategy"],
        "strategy_x_granularity": ["strategy", "granularity"],
        "task": ["task_id"],
    }[args.by]

    agg = (
        df.group_by(group_cols)
        .agg(
            n=pl.len(),
            success=pl.col("success").cast(pl.Float64).mean(),
            avg_cost=pl.col("total_cost_usd").mean(),
            avg_latency_s=(pl.col("total_latency_ms") / 1000).mean(),
            avg_surfaced=pl.col("surfaced_count").mean(),
            hall=pl.col("hallucinated").list.len().cast(pl.Float64).mean(),
            forb=pl.col("forbidden_called").list.len().cast(pl.Float64).mean(),
            schemabad=pl.col("schema_invalid").list.len().cast(pl.Float64).mean(),
        )
        .sort(["success", "avg_cost"], descending=[True, False])
    )

    print(f"### Sorted by success (then cost ascending) — group_by={group_cols}\n")
    print(f"{'rank':<5}{'strategy':<46}{'gran':<7}{'n':>4} {'succ%':>6} {'$/q':>9} {'lat_s':>7} {'surf':>5} {'hall':>5} {'forb':>5} {'sch':>5}")
    print("-" * 110)
    for i, row in enumerate(agg.iter_rows(named=True), start=1):
        gran = row.get("granularity", "-")
        print(
            f"{i:<5}{row.get('strategy', row.get('task_id', '?'))[:45]:<46}{gran:<7}{row['n']:>4} "
            f"{100*row['success']:>5.0f}% {row['avg_cost']:>9.4f} {row['avg_latency_s']:>7.2f} "
            f"{row['avg_surfaced']:>5.1f} {row['hall']:>5.2f} {row['forb']:>5.2f} {row['schemabad']:>5.2f}"
        )

    # Per-difficulty breakdown
    if "task_difficulty" in df.columns and args.by != "task":
        print("\n\n### Per-difficulty success rate")
        per = (
            df.group_by(["strategy", "task_difficulty"])
            .agg(success=pl.col("success").cast(pl.Float64).mean(), n=pl.len())
            .pivot(values="success", index="strategy", on="task_difficulty")
            .sort("strategy")
        )
        print(per)

    return 0


if __name__ == "__main__":
    sys.exit(main())
