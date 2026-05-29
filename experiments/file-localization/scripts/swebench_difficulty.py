"""Derive per-instance difficulty from the SWE-Bench leaderboard.

The `swe-bench/experiments` GitHub repo stores every submission's
results as JSON. Each `results.json` has a `resolved` array of
instance IDs the submission solved. Across N submissions, an
instance's pass-rate is `resolved_count / N`.

This script:
  1. Lists submission dirs from github.com/swe-bench/experiments
  2. Fetches each `results.json` (parallelizable)
  3. Aggregates pass-rate per instance ID
  4. Writes a CSV sorted by pass-rate ascending — hardest first

Usage:
    uv run --package file-localization python \\
        experiments/file-localization/scripts/swebench_difficulty.py \\
        --split lite \\
        --since 20240601 \\
        --out lib/agent-eval-core/data/swebench_lite_difficulty.csv

`--since YYYYMMDD` filters submissions by date prefix — the leaderboard
includes a lot of early RAG baselines that resolve almost nothing.
Excluding them gives a more honest "is this task hard or are agents
just bad" signal.

Output columns: instance_id, repo, n_solved, n_total, pass_rate.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import re
import subprocess
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path


_REPO = "swe-bench/experiments"
_RAW_BASE = f"https://raw.githubusercontent.com/{_REPO}/main"


def _list_submissions(split: str) -> list[str]:
    """Use `gh api` to list submission directories under evaluation/<split>/."""
    out = subprocess.check_output(
        ["gh", "api", f"repos/{_REPO}/contents/evaluation/{split}", "--jq", ".[].name"],
        text=True,
    )
    return [n.strip() for n in out.splitlines() if n.strip()]


def _filter_since(names: list[str], since: str | None) -> list[str]:
    """Keep only dirs whose YYYYMMDD prefix is >= since."""
    if not since:
        return names
    return [n for n in names if (m := re.match(r"^(\d{8})", n)) and m.group(1) >= since]


def _fetch_results(split: str, sub_dir: str, timeout: int = 30) -> tuple[str, list[str] | None]:
    """Download one submission's results.json and return its `resolved` list.

    Returns (sub_dir, resolved) on success, (sub_dir, None) on failure.
    """
    url = f"{_RAW_BASE}/evaluation/{split}/{sub_dir}/results/results.json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.load(r)
    except Exception as e:  # noqa: BLE001
        print(f"  [skip] {sub_dir}: {type(e).__name__}: {e}", file=sys.stderr)
        return sub_dir, None
    resolved = data.get("resolved")
    if not isinstance(resolved, list):
        print(f"  [skip] {sub_dir}: no `resolved` array", file=sys.stderr)
        return sub_dir, None
    return sub_dir, [str(x) for x in resolved]


def _load_instance_universe(split: str) -> list[tuple[str, str]]:
    """Load (instance_id, repo) for every task in the split.

    Returns the canonical universe — instances not solved by ANY
    submission still appear in the output (with pass_rate = 0).
    """
    # Lazy import: don't force HF dataset deps when only listing submissions.
    from file_localization.adapters import load_swebench

    raw = load_swebench(split, split="test")
    return [(t.instance_id, t.repo) for t in raw]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", choices=["lite", "verified"], default="verified")
    p.add_argument(
        "--since",
        default=None,
        help="YYYYMMDD prefix filter — drop submissions older than this date "
        "(e.g. '20240601' excludes early RAG baselines). Default: keep all.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output CSV path. Default: results/swebench_<split>_difficulty.csv",
    )
    p.add_argument(
        "--parallelism",
        type=int,
        default=8,
        help="Concurrent HTTP fetches",
    )
    args = p.parse_args()

    out = args.out or Path(f"results/swebench_{args.split}_difficulty.csv")

    print(f"listing submissions in evaluation/{args.split}/...", file=sys.stderr)
    subs_all = _list_submissions(args.split)
    subs = _filter_since(subs_all, args.since)
    print(
        f"  {len(subs_all)} total, {len(subs)} after --since {args.since or '(none)'}",
        file=sys.stderr,
    )

    print(f"fetching results.json from {len(subs)} submissions...", file=sys.stderr)
    resolved_by_sub: dict[str, list[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallelism) as pool:
        futs = {pool.submit(_fetch_results, args.split, s): s for s in subs}
        for fut in concurrent.futures.as_completed(futs):
            sub_dir, resolved = fut.result()
            if resolved is not None:
                resolved_by_sub[sub_dir] = resolved
    n_subs = len(resolved_by_sub)
    print(f"  loaded {n_subs} successful submissions", file=sys.stderr)

    if n_subs == 0:
        print("ERROR: no submissions loaded; nothing to do", file=sys.stderr)
        return 1

    # Per-instance: count submissions that resolved it.
    solved_count: dict[str, int] = defaultdict(int)
    for resolved in resolved_by_sub.values():
        for inst in set(resolved):  # de-dupe within one submission
            solved_count[inst] += 1

    print("loading the instance universe (HF dataset)...", file=sys.stderr)
    universe = _load_instance_universe(args.split)
    rows: list[tuple[str, str, int, int, float]] = []
    for inst_id, repo in universe:
        n = solved_count.get(inst_id, 0)
        rows.append((inst_id, repo, n, n_subs, n / n_subs))

    # Hardest first.
    rows.sort(key=lambda r: (r[4], r[0]))

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["instance_id", "repo", "n_solved", "n_total", "pass_rate"])
        for inst_id, repo, n, total, rate in rows:
            w.writerow([inst_id, repo, n, total, f"{rate:.4f}"])
    print(f"\nwrote {len(rows)} rows to {out}", file=sys.stderr)

    # Quick console summary of the hardest 20.
    print("\nHardest 20 instances:", file=sys.stderr)
    print(f"  {'instance_id':<40} {'repo':<30} {'pass_rate':>10}", file=sys.stderr)
    for inst_id, repo, n, total, rate in rows[:20]:
        print(f"  {inst_id:<40} {repo:<30} {rate:>9.1%} ({n}/{total})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
