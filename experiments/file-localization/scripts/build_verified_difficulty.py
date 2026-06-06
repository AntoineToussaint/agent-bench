"""Build a *model-solvability* difficulty signal for SWE-bench Verified.

Why this exists (replaces the leaderboard scraper for Verified)
---------------------------------------------------------------
`swebench_difficulty.py` derived difficulty from the public leaderboard
(`pass_rate = resolved_submissions / N`). For SWE-bench Verified that signal
turned out to be **non-discriminative**: mean reference-model solve-rate is
flat (~0.62-0.69) across every leaderboard band, and 22 tasks marked `0/125`
are solved by >=3 of 4 strong models. The leaderboard column is dominated by
stale / partial early submissions and by instances simply missing from many
submission sets (32 spurious `0/125`s), so it carries almost no information
about how hard a task is for a capable agent.

This script instead derives difficulty from signals we *trust*, all already
sitting locally in `swebench_verified_enrichment.csv` (no network needed):

  * `ref_solve_rate` — fraction of 4 strong reference models (gpt-5, gpt-5-mini,
    sonnet-4, sonnet-4.5) that resolved the task. This is the primary signal.
  * `ref_cost_avg` and per-model `calls_*` — how much compute even *successful*
    runs burned (effort proxy; breaks ties within a solve-rate tier).
  * human time-to-fix bucket — intrinsic difficulty (final tie-break).
  * OpenAI annotation flags — mark tasks whose *pass/fail signal* is suspect
    (`flagged=1`) so consumers can drop them rather than mistaking them for
    "hard". NOTE: the enrichment copies OpenAI's ensembled annotations verbatim,
    and those columns are binary 0/1 majority votes (not 0-3 severities). We
    flag on `false_negative` / `other_major_issues` only — `underspecified`
    (~half the set) is left *in* the ranking: a model that can't infer the
    intended fix from an underspecified issue is legitimately harder, not broken.

Output (superset of the old schema — drop-in for `CsvDifficultySource` /
`band_instance_ids`, which only read instance_id / pass_rate / n_solved /
n_total):

    instance_id, repo, n_solved, n_total, pass_rate,
    difficulty_score, band, human_bucket, ref_cost_avg, avg_calls, flagged

  * `pass_rate`  = ref_solve_rate (so existing band thresholds still apply:
    0 = unsolved, <=0.25 = hard (== 1/4), <=0.75 = medium, else easy).
  * `n_solved`/`n_total` = ref models that solved / 4.
  * `difficulty_score` in [0,1], **1 = hardest**. A rank-percentile over the
    sort key (solve-rate asc, cost desc, calls desc, human-time desc) — so
    solve-rate strictly dominates, then cost, then calls, then human time.
  * `flagged` = 1 if `underspecified` or `false_negative` severity >= 2.

Rows are sorted hardest-first.

Usage (no network, no `gh`):

    uv run --package file-localization python \\
        experiments/file-localization/scripts/build_verified_difficulty.py \\
        --enrichment lib/agent-eval-core/data/swebench_verified_enrichment.csv \\
        --out lib/agent-eval-core/data/swebench_verified_difficulty.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Reference models whose per-instance resolution drives the solve-rate.
_REF_MODELS = ("gpt5", "gpt5_mini", "sonnet4", "sonnet45")

# Human time-to-fix bucket -> normalized intrinsic-difficulty weight.
_HUMAN_NORM = {
    "<15 min fix": 0.0,
    "15 min - 1 hour": 0.34,
    "1-4 hours": 0.67,
    ">4 hours": 1.0,
}

# OpenAI annotation flags (binary 0/1) that make a task's pass/fail signal
# suspect. `underspecified` is intentionally excluded — it's intrinsic
# difficulty, not contamination (see module docstring).
_SIGNAL_FLAGS = ("false_negative", "other_major_issues")
_FLAG_THRESHOLD = 1.0


def _repo_from_instance(instance_id: str) -> str:
    """`astropy__astropy-13398` -> `astropy/astropy`; `pylint-dev__pylint-4604`
    -> `pylint-dev/pylint`. Format is `{org}__{name}-{number}`."""
    org, _, rest = instance_id.partition("__")
    if not rest:
        return instance_id
    name = rest.rsplit("-", 1)[0]
    return f"{org}/{name}"


def _f(v: str | None) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _truthy(v: str | None) -> bool:
    return v in ("1", "1.0", "True", "true")


def _percentiles(values: list[float | None]) -> dict[int, float]:
    """Map each row index -> percentile rank in [0,1] of its value (None -> 0).

    Ties share the average rank; a column that is entirely None yields all 0.0
    (so it contributes nothing to the ordering)."""
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    if not present:
        return {i: 0.0 for i in range(len(values))}
    order = sorted(present, key=lambda iv: iv[1])
    out: dict[int, float] = {i: 0.0 for i in range(len(values))}
    n = len(order)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and order[j + 1][1] == order[i][1]:
            j += 1
        # average percentile for this tie group
        rank = (i + j) / 2.0
        pct = rank / (n - 1) if n > 1 else 0.0
        for k in range(i, j + 1):
            out[order[k][0]] = pct
        i = j + 1
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--enrichment",
        type=Path,
        default=Path("lib/agent-eval-core/data/swebench_verified_enrichment.csv"),
        help="Input enrichment CSV (built by build_verified_enrichment.py).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("lib/agent-eval-core/data/swebench_verified_difficulty.csv"),
        help="Output difficulty CSV.",
    )
    args = p.parse_args()

    with args.enrichment.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print(f"ERROR: no rows in {args.enrichment}", file=sys.stderr)
        return 1

    # First pass: pull the raw per-task signals.
    recs = []
    for r in rows:
        iid = r["instance_id"]
        n_solved = sum(1 for m in _REF_MODELS if _truthy(r.get(f"resolved_{m}")))
        calls = [_f(r.get(f"calls_{m}")) for m in _REF_MODELS]
        calls_present = [c for c in calls if c is not None]
        avg_calls = sum(calls_present) / len(calls_present) if calls_present else None
        sev = max((_f(r.get(k)) or 0.0) for k in _SIGNAL_FLAGS)
        recs.append(
            {
                "instance_id": iid,
                "repo": _repo_from_instance(iid),
                "n_solved": n_solved,
                "n_total": len(_REF_MODELS),
                "pass_rate": n_solved / len(_REF_MODELS),
                "human_bucket": r.get("difficulty", ""),
                "human_norm": _HUMAN_NORM.get(r.get("difficulty", ""), 0.0),
                "ref_cost_avg": _f(r.get("ref_cost_avg")),
                "avg_calls": avg_calls,
                "flagged": 1 if sev >= _FLAG_THRESHOLD else 0,
            }
        )

    # Percentile ranks for the tie-break signals (cost, calls).
    cost_pct = _percentiles([rec["ref_cost_avg"] for rec in recs])
    calls_pct = _percentiles([rec["avg_calls"] for rec in recs])

    # Sort key: solve-rate asc (primary), then cost desc, calls desc, human desc,
    # then instance_id for determinism. Hardest ends up first.
    def sort_key(i_rec):
        i, rec = i_rec
        return (
            rec["pass_rate"],
            -cost_pct[i],
            -calls_pct[i],
            -rec["human_norm"],
            rec["instance_id"],
        )

    ordered = sorted(enumerate(recs), key=sort_key)

    # difficulty_score = rank percentile, 1.0 = hardest (first after sort).
    n = len(ordered)
    for pos, (_, rec) in enumerate(ordered):
        rec["difficulty_score"] = round(1.0 - pos / (n - 1), 4) if n > 1 else 1.0
        # band from pass_rate, matching agent_eval.difficulty.band_for defaults.
        pr = rec["pass_rate"]
        rec["band"] = (
            "unsolved" if pr <= 0 else "hard" if pr <= 0.25 else "medium" if pr <= 0.75 else "easy"
        )

    cols = [
        "instance_id",
        "repo",
        "n_solved",
        "n_total",
        "pass_rate",
        "difficulty_score",
        "band",
        "human_bucket",
        "ref_cost_avg",
        "avg_calls",
        "flagged",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for _, rec in ordered:
            w.writerow(
                [
                    rec["instance_id"],
                    rec["repo"],
                    rec["n_solved"],
                    rec["n_total"],
                    f"{rec['pass_rate']:.4f}",
                    f"{rec['difficulty_score']:.4f}",
                    rec["band"],
                    rec["human_bucket"],
                    "" if rec["ref_cost_avg"] is None else f"{rec['ref_cost_avg']:.4f}",
                    "" if rec["avg_calls"] is None else f"{rec['avg_calls']:.2f}",
                    rec["flagged"],
                ]
            )

    # Console summary.
    from collections import Counter

    bands = Counter(rec["band"] for _, rec in ordered)
    flagged = sum(rec["flagged"] for _, rec in ordered)
    print(f"wrote {n} rows to {args.out}", file=sys.stderr)
    print(f"  bands: {dict(bands)}  flagged: {flagged}", file=sys.stderr)
    print("\nHardest 10 (model-solvability):", file=sys.stderr)
    print(
        f"  {'instance_id':<34}{'score':>7}{'pass':>7}{'band':>10}{'  human':<16}  flag",
        file=sys.stderr,
    )
    for _, rec in ordered[:10]:
        print(
            f"  {rec['instance_id']:<34}{rec['difficulty_score']:>7.3f}"
            f"{rec['pass_rate']:>7.2f}{rec['band']:>10}  {rec['human_bucket']:<16}"
            f"{'  FLAG' if rec['flagged'] else ''}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
