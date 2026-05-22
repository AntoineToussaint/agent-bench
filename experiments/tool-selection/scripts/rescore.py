"""Re-score an existing sweep JSONL with the current scorer (no API calls).

Reads each row's task_id + granularity + final_calls + surfaced_tools, looks
up the Task and Catalog, runs `scorer.score()` to compute current metrics
(including the new selection_matched), and writes a new JSONL with the
updated scoring fields. Cost data and pipeline info are preserved.

Usage:
    uv run python scripts/rescore.py data/runs/sweep_haiku.jsonl
        -> writes data/runs/sweep_haiku.rescored.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tool_selection.catalogs import CATALOGS
from tool_selection.scorer import score
from tool_selection.tasks import by_id
from tool_selection.types import CallTrace


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    out_path = args.out or args.input.with_name(args.input.stem + ".rescored.jsonl")
    if out_path.exists():
        out_path.unlink()

    n_in = 0
    n_out = 0
    n_changed = 0
    with args.input.open() as f_in, out_path.open("w") as f_out:
        for line in f_in:
            row = json.loads(line)
            n_in += 1
            try:
                task = by_id(row["task_id"])
            except KeyError:
                # Task removed since the run — pass through unchanged
                f_out.write(line)
                n_out += 1
                continue

            catalog = CATALOGS[row["granularity"]]
            trace = CallTrace(
                task_id=row["task_id"],
                approach_id=row["strategy"],
                granularity=row["granularity"],
                final_model=row["model"],
                surfaced_tools=row.get("surfaced_tools") or [],
                final_calls=row.get("final_calls") or [],
            )
            sc = score(trace, task, catalog)

            # Overwrite scoring fields, preserve everything else
            new = dict(row)
            old_success = row.get("success")
            new["success"] = sc.task_success
            new["required_total"] = sc.required_total
            new["required_matched"] = sc.required_matched
            new["selection_matched"] = sc.selection_matched
            new["selection_accuracy"] = sc.selection_accuracy
            new["args_accuracy_given_selection"] = sc.args_accuracy_given_selection
            new["missing"] = sc.missing_required
            new["hallucinated"] = sc.hallucinated_calls
            new["extras"] = sc.extra_calls
            new["forbidden_called"] = sc.forbidden_called
            new["schema_invalid"] = sc.schema_invalid_calls

            if old_success is not None and old_success != sc.task_success:
                n_changed += 1

            f_out.write(json.dumps(new) + "\n")
            n_out += 1

    print(f"Rescored {n_in} rows -> {out_path} ({n_out} written, {n_changed} success-flag changes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
