"""WHERE does diff beat rewrite? Regress the diff advantage (cost & latency)
against model-independent LOCALITY features, to find the crossover.

Hypothesis: diff wins iff its patch is shorter than re-emitting the changed
file — i.e. large `changed_file_chars` with small `edit_fraction`. Below a
file-size crossover the search_replace diff's per-hunk overhead makes it LOSE.

For each task_id (which encodes size, e.g. c06..._large) it averages the diff
conditions and the rewrite conditions over reps+ladders, then prints rows sorted
by changed_file_chars so the crossover is visible as a sign change in Δ.

Usage:
  uv run --package code-editing python \
    experiments/code-editing/scripts/analyze_locality.py \
    results/patch_cascade_locality/per_trial.csv
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: analyze_locality.py <per_trial.csv>", file=sys.stderr)
        return 1
    rows = list(csv.DictReader(Path(sys.argv[1]).open()))

    # group per task_id, split diff vs rewrite
    by_task: dict[str, dict[str, list[dict]]] = defaultdict(lambda: {"diff": [], "rewrite": []})
    for r in rows:
        kind = "diff" if "diff" in r["condition"] else ("rewrite" if "rewrite" in r["condition"] else None)
        if kind:
            by_task[r["task_id"]][kind].append(r)

    def fmean(rs, col):
        v = [float(r[col]) for r in rs if r.get(col) not in (None, "")]
        return sum(v) / len(v) if v else float("nan")

    recs = []
    for task, grp in by_task.items():
        d, rw = grp["diff"], grp["rewrite"]
        if not d or not rw:
            continue
        # locality from the diff runs (true minimal-patch size vs file size)
        recs.append({
            "task": task,
            "file_chars": fmean(d, "changed_file_chars"),
            "edit_frac": fmean(d, "edit_fraction"),
            "draft_fail": fmean(d, "draft_failing_tests"),
            "d_out": fmean(d, "top_tier_output_tokens"),
            "rw_out": fmean(rw, "top_tier_output_tokens"),
            "d_cost": fmean(d, "cost_usd"),
            "rw_cost": fmean(rw, "cost_usd"),
            "d_lat": fmean(d, "latency_s"),
            "rw_lat": fmean(rw, "latency_s"),
            "d_pass": fmean(d, "passed"),
            "rw_pass": fmean(rw, "passed"),
        })

    recs.sort(key=lambda x: x["file_chars"])
    print(f"{'task':30s} {'file_ch':>8s} {'edit_f':>6s} {'dfail':>5s} | "
          f"{'d_out':>6s} {'rw_out':>6s} {'out×':>5s} | "
          f"{'Δcost%':>7s} {'Δlat%':>6s} | {'pass d/rw':>9s}")
    print("-" * 100)
    for r in recs:
        cost_win = (r["rw_cost"] - r["d_cost"]) / r["rw_cost"] * 100 if r["rw_cost"] else 0
        lat_win = (r["rw_lat"] - r["d_lat"]) / r["rw_lat"] * 100 if r["rw_lat"] else 0
        out_ratio = r["rw_out"] / r["d_out"] if r["d_out"] else 0
        print(f"{r['task'][:30]:30s} {r['file_chars']:8.0f} {r['edit_frac']:6.2f} "
              f"{r['draft_fail']:5.1f} | {r['d_out']:6.0f} {r['rw_out']:6.0f} {out_ratio:4.1f}x | "
              f"{cost_win:+6.0f}% {lat_win:+5.0f}% | {r['d_pass']:.2f}/{r['rw_pass']:.2f}")

    # crude crossover read: smallest file where Δcost turns positive
    pos = [r for r in recs if (r["rw_cost"] - r["d_cost"]) > 0]
    neg = [r for r in recs if (r["rw_cost"] - r["d_cost"]) <= 0]
    if pos and neg:
        print(f"\ncrossover (cost): diff LOSES up to ~{max(r['file_chars'] for r in neg):.0f} "
              f"changed chars, WINS from ~{min(r['file_chars'] for r in pos):.0f} up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
