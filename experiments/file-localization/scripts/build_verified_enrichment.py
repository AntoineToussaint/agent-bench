"""Build a per-instance enrichment CSV for SWE-bench Verified.

Public SWE-bench data has no latency or token counts, but it DOES have, per
instance: human difficulty (time-to-fix bucket), OpenAI's quality-annotation
flags (underspecified / false-negative tests / other issues), and — for the 4
reference mini-SWE-agent models — dollar cost + API calls + resolved. This
script fetches those, joins on instance_id, and writes a slim CSV.

Sources (all fetched live; nothing large is committed — only the derived join):
  - OpenAI annotations zip (difficulty + quality flags), 1699 test ids:
    https://cdn.openai.com/introducing-swe-bench-verified/swe-bench-annotation-results.zip
    -> ensembled_annotations_public.csv
  - Per-instance cost/calls for gpt-5, gpt-5-mini, sonnet-4, sonnet-4-5
    (the Verified 500, mini-SWE-agent scaffold):
    https://raw.githubusercontent.com/swe-bench/swe-bench.github.io/master/data/info_for_leaderboard.json

The Verified-500 membership is taken as the instance_id set in
info_for_leaderboard.json (those 4 models ran on exactly the 500).

NOTE on licensing: neither source declares a license. We commit only derived
factual columns (difficulty bucket, 0-3 flag severities, cost floats), no raw
annotator notes / user ids / timestamps. Cite the sources; keep raw archives
out of git.

Usage:
    uv run --package file-localization python \\
        experiments/file-localization/scripts/build_verified_enrichment.py \\
        --out lib/agent-eval-core/data/swebench_verified_enrichment.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

_ANNOTATION_ZIP = (
    "https://cdn.openai.com/introducing-swe-bench-verified/"
    "swe-bench-annotation-results.zip"
)
_LEADERBOARD_COST = (
    "https://raw.githubusercontent.com/swe-bench/swe-bench.github.io/"
    "master/data/info_for_leaderboard.json"
)

# Model keys in info_for_leaderboard.json -> column-safe suffix.
_MODEL_COLS = {
    "gpt-5": "gpt5",
    "gpt-5-mini": "gpt5_mini",
    "sonnet-4": "sonnet4",
    "sonnet-4-5": "sonnet45",
}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "agent-bench/enrichment"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _fetch_annotations() -> dict[str, dict[str, str]]:
    """instance_id -> {difficulty, underspecified, false_negative, other_major_issues}."""
    raw = _get(_ANNOTATION_ZIP)
    zf = zipfile.ZipFile(io.BytesIO(raw))
    name = next(n for n in zf.namelist() if n.endswith("ensembled_annotations_public.csv"))
    text = zf.read(name).decode("utf-8")
    out: dict[str, dict[str, str]] = {}
    for row in csv.DictReader(io.StringIO(text)):
        out[row["instance_id"]] = {
            "difficulty": row.get("difficulty", ""),
            "underspecified": row.get("underspecified", ""),
            "false_negative": row.get("false_negative", ""),
            "other_major_issues": row.get("other_major_issues", ""),
        }
    return out


def _fetch_costs() -> dict[str, dict[str, dict]]:
    """model -> instance_id -> {resolved, cost, api_calls}."""
    return json.loads(_get(_LEADERBOARD_COST).decode("utf-8"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--out",
        type=Path,
        default=Path("lib/agent-eval-core/data/swebench_verified_enrichment.csv"),
    )
    args = p.parse_args()

    print("fetching OpenAI annotations...", flush=True)
    ann = _fetch_annotations()
    print(f"  {len(ann)} annotated instances", flush=True)

    print("fetching per-instance cost (4 reference models)...", flush=True)
    costs = _fetch_costs()
    present = {m: costs.get(m, {}) for m in _MODEL_COLS}
    # Verified-500 membership = union of instance ids across the 4 model runs.
    verified_ids = sorted(set().union(*(set(d) for d in present.values())))
    print(f"  {len(verified_ids)} instances with cost data", flush=True)

    fieldnames = [
        "instance_id",
        "difficulty",
        "underspecified",
        "false_negative",
        "other_major_issues",
        "ref_solve_rate",   # fraction of the 4 ref models that resolved it
        "ref_cost_avg",     # mean $/instance across the 4 ref models
    ]
    for suffix in _MODEL_COLS.values():
        fieldnames += [f"cost_{suffix}", f"calls_{suffix}", f"resolved_{suffix}"]

    rows = []
    for iid in verified_ids:
        a = ann.get(iid, {})
        row = {
            "instance_id": iid,
            "difficulty": a.get("difficulty", ""),
            "underspecified": a.get("underspecified", ""),
            "false_negative": a.get("false_negative", ""),
            "other_major_issues": a.get("other_major_issues", ""),
        }
        costs_here, resolved_flags = [], []
        for model, suffix in _MODEL_COLS.items():
            cell = present[model].get(iid)
            if cell:
                row[f"cost_{suffix}"] = cell.get("cost", "")
                row[f"calls_{suffix}"] = cell.get("api_calls", "")
                row[f"resolved_{suffix}"] = int(bool(cell.get("resolved")))
                if isinstance(cell.get("cost"), (int, float)):
                    costs_here.append(float(cell["cost"]))
                resolved_flags.append(bool(cell.get("resolved")))
            else:
                row[f"cost_{suffix}"] = ""
                row[f"calls_{suffix}"] = ""
                row[f"resolved_{suffix}"] = ""
        row["ref_solve_rate"] = (
            round(sum(resolved_flags) / len(resolved_flags), 4) if resolved_flags else ""
        )
        row["ref_cost_avg"] = round(sum(costs_here) / len(costs_here), 4) if costs_here else ""
        rows.append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    size_kb = args.out.stat().st_size / 1024
    print(f"\nwrote {len(rows)} rows -> {args.out} ({size_kb:.0f} KB)", flush=True)
    # Quick sanity: difficulty distribution.
    from collections import Counter

    dist = Counter(r["difficulty"] for r in rows)
    print("difficulty distribution:", dict(dist))
    return 0


if __name__ == "__main__":
    sys.exit(main())
