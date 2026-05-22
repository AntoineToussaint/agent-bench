"""End-to-end smoke test: run the 'full' approach on all tasks with one
cheap model in narrow granularity. Print one-line results per task and
total cost. Designed to be < $0.10 total.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from tool_selection.approaches import APPROACHES
from tool_selection.catalogs import narrow_catalog
from tool_selection.runner import run_one, write_trace_jsonl
from tool_selection.tasks import ALL_TASKS

load_dotenv()

MODEL = os.environ.get("SHAKEDOWN_MODEL", "claude-haiku-4-5")


def main() -> int:
    approach = APPROACHES["full"]()
    results = []
    total_cost = 0.0
    succ = 0

    print(f"Shakedown: approach={approach.id}, model={MODEL}, granularity=narrow")
    print(f"Tasks: {len(ALL_TASKS)}")
    print("-" * 96)

    for task in ALL_TASKS:
        trace, sc = run_one(approach, narrow_catalog, MODEL, task)
        results.append((trace, sc))
        total_cost += trace.total_cost_usd
        if sc.task_success:
            succ += 1
        flag = "OK " if sc.task_success else "FAIL"
        print(
            f"  [{flag}] {task.id:40s} matched={sc.required_matched}/{sc.required_total} "
            f"hall={len(sc.hallucinated_calls)} forb={len(sc.forbidden_called)} "
            f"schema_bad={len(sc.schema_invalid_calls)} extra={len(sc.extra_calls)} "
            f"calls={len(trace.final_calls)} cost=${trace.total_cost_usd:.4f} "
            f"lat={trace.total_latency_ms:.0f}ms"
        )
        if not sc.task_success and (sc.missing_required or sc.forbidden_called):
            print(f"         missing={sc.missing_required} forb={sc.forbidden_called}")

    print("-" * 96)
    print(f"Success: {succ}/{len(ALL_TASKS)}  Total cost: ${total_cost:.4f}")

    out = Path("data/runs/shakedown.jsonl")
    write_trace_jsonl(results, out)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
