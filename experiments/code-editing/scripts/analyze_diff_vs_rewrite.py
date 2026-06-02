"""Characterize WHEN diff-correction beats rewrite (regeneration), on COST and
LATENCY separately.

The diff knob's whole premise: a correction emits fewer output tokens than a
full rewrite. Output tokens cost money AND take wall-clock. So the diff
advantage on both axes should scale with how much SHORTER the diff's top-tier
output is than the rewrite's — which in turn scales with file size and edit
locality. This script pairs (diff, rewrite) at the same ladder+gating and prints
 delta-cost, delta-latency, and the output-token gap that drives them.

Usage:
  uv run --package code-editing python \
    experiments/code-editing/scripts/analyze_diff_vs_rewrite.py \
    results/patch_cascade_diffvsrewrite/per_trial.csv \
    results/patch_cascade_large/per_trial.csv
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path


def _load(path: Path):
    rows = list(csv.DictReader(path.open()))
    # mean over reps, keyed by (task_id, condition)
    agg: dict[tuple[str, str], dict[str, float]] = {}
    bucket = defaultdict(list)
    for r in rows:
        bucket[(r["task_id"], r["condition"])].append(r)
    for key, rs in bucket.items():
        n = len(rs)
        def m(col):
            vals = [float(r[col]) for r in rs if r.get(col) not in (None, "")]
            return sum(vals) / len(vals) if vals else 0.0
        agg[key] = {
            "pass": m("passed"),
            "cost": m("cost_usd"),
            "lat": m("latency_s"),
            "top_out": m("top_tier_output_tokens"),
            "n": n,
        }
    return agg


# ladder/gating variants -> the (diff_condition, rewrite_condition) pair
PAIRS = [
    ("2-tier",        "cascade-2-diff",        "cascade-2-rewrite"),
    ("3-tier",        "cascade-3-diff",        "cascade-3-rewrite"),
    ("2-tier gated",  "cascade-2-diff-gated",  "cascade-2-rewrite-gated"),
    ("3-tier gated",  "cascade-3-diff-gated",  "cascade-3-rewrite-gated"),
]


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print("usage: analyze_diff_vs_rewrite.py <per_trial.csv> [more.csv ...]", file=sys.stderr)
        return 1

    for path in paths:
        agg = _load(path)
        tasks = sorted({k[0] for k in agg})
        print(f"\n########## {path}")
        print(f"{'task':28s} {'variant':14s} | "
              f"{'diff$':>8s} {'rw$':>8s} {'Δ$%':>6s} | "
              f"{'diffs':>6s} {'rws':>6s} {'Δlat%':>6s} | "
              f"{'d_out':>6s} {'rw_out':>6s} | pass")
        print("-" * 104)
        for task in tasks:
            for label, dcond, rcond in PAIRS:
                d = agg.get((task, dcond))
                r = agg.get((task, rcond))
                if not d or not r:
                    continue
                dc, rc = d["cost"], r["cost"]
                dl, rl = d["lat"], r["lat"]
                cost_win = (rc - dc) / rc * 100 if rc else 0.0   # >0 => diff cheaper
                lat_win = (rl - dl) / rl * 100 if rl else 0.0    # >0 => diff faster
                passes = f"{d['pass']:.2f}/{r['pass']:.2f}"
                print(f"{task[:28]:28s} {label:14s} | "
                      f"${dc:7.4f} ${rc:7.4f} {cost_win:+5.0f}% | "
                      f"{dl:5.1f}s {rl:5.1f}s {lat_win:+5.0f}% | "
                      f"{d['top_out']:6.0f} {r['top_out']:6.0f} | {passes}")
        # headline: mean diff-advantage on each axis
        cwins, lwins = [], []
        for task in tasks:
            for _l, dcond, rcond in PAIRS:
                d, r = agg.get((task, dcond)), agg.get((task, rcond))
                if d and r and r["cost"] and r["lat"]:
                    cwins.append((r["cost"] - d["cost"]) / r["cost"] * 100)
                    lwins.append((r["lat"] - d["lat"]) / r["lat"] * 100)
        if cwins:
            print(f"\n  mean diff advantage:  cost {sum(cwins)/len(cwins):+.0f}%   "
                  f"latency {sum(lwins)/len(lwins):+.0f}%   (over {len(cwins)} pairs; "
                  f"+ = diff better)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
