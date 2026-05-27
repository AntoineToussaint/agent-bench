"""Export observed failure cases as a YAML fixture file.

Walks one or more results/ directories, reads each `per_trial.csv` plus
its OTEL trace file, and for every FAILED trial extracts:

  - task identity (instance_id, repo, base_commit, gold files, issue text)
  - observed-when context (model, condition/backend)
  - diagnosed failure mode (from classify_trace; falls back to classify_output)
  - reference signal (what the agent actually submitted)

Output is one YAML entry per failure, intended for downstream testing:
point your own agent at these task fixtures and check whether it
exhibits the same failure modes.

Usage:
    uv run --package file-localization python \
        experiments/file-localization/scripts/export_failure_fixtures.py \
        results/protocol_matrix_v2 \
        [results/cmp_14995_sonnet ...] \
        --out lib/agent-eval-core/data/failure_fixtures.yaml
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from agent_eval.failure_modes import classify_output, classify_trace
from file_localization.adapters import load_swebench, to_localization_tasks
from file_localization.contract import LocalizationTask


def _index_tasks() -> dict[str, LocalizationTask]:
    """Load SWE-Bench Lite once and index by instance_id."""
    print("loading SWE-Bench Lite (split=test) for issue-text lookup...",
          file=sys.stderr, flush=True)
    raw = load_swebench("lite", split="test")
    tasks = to_localization_tasks(raw)
    return {t.instance_id: t for t in tasks}


def _load_spans(trace_path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()]


def _find_trial_span(
    spans: list[dict[str, Any]],
    *,
    task_id: str,
    condition: str,
    model: str,
    replicate: int,
) -> dict[str, Any] | None:
    for s in spans:
        if s["name"] != "trial":
            continue
        a = s.get("attrs", {})
        if (
            a.get("agent_eval.task.id") == task_id
            and a.get("agent_eval.condition") == condition
            and a.get("gen_ai.request.model") == model
            and int(a.get("agent_eval.replicate") or 0) == int(replicate)
        ):
            return s
    return None


def _submitted_from_trial(
    spans: list[dict[str, Any]],
    trial_span: dict[str, Any],
) -> list[str]:
    """Find the trial's `done` tool_call and return the submitted file list.

    The trial loop dispatches `done` as the terminal tool; its args carry
    `{"files": [...]}`. Walk: trial → turns → tool_calls, find the
    tool_call named `done`, parse its `agent_eval.tool.args` JSON.
    """
    turn_ids = {
        s["span_id"]
        for s in spans
        if s.get("parent_span_id") == trial_span["span_id"] and s["name"] == "turn"
    }
    for s in spans:
        if s["name"] != "tool_call":
            continue
        if s.get("parent_span_id") not in turn_ids:
            continue
        attrs = s.get("attrs", {})
        if attrs.get("agent_eval.tool.name") != "done":
            continue
        args_json = attrs.get("agent_eval.tool.args") or "{}"
        try:
            args = json.loads(args_json) if isinstance(args_json, str) else args_json
        except (ValueError, TypeError):
            continue
        files = args.get("files") if isinstance(args, dict) else None
        if isinstance(files, list):
            return [str(f) for f in files]
    return []


def _format_entry(
    *,
    row: dict[str, str],
    task: LocalizationTask | None,
    failure_mode: str | None,
    submitted: list[str],
    backend: str,
    source_run: str,
) -> dict[str, Any]:
    instance_id = row["task_id"]
    case_id = f"{instance_id}-{failure_mode or 'unclassified'}-{row['condition']}-{row['model']}"
    entry: dict[str, Any] = {
        "case_id": case_id,
        "task": {
            "instance_id": instance_id,
            "repo": task.repo if task else None,
            "base_commit": task.base_commit if task else None,
            "gold_edit_files": sorted(task.gold_edit_files) if task else None,
            "issue_text": task.issue_text if task else None,
        },
        "observed_when": {
            "model": row["model"],
            "condition": row["condition"],
            "backend": backend,
            "source_run": source_run,
        },
        "failure_mode": failure_mode,
        "reference_signal": {
            "submitted_files": submitted,
            "turns": int(row.get("turns") or 0),
            "tool_calls": int(row.get("tool_calls") or 0),
            "cost_usd": float(row.get("cost_usd") or 0),
            "error": row.get("error") or None,
        },
    }
    return entry


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "results_dirs",
        nargs="+",
        type=Path,
        help="one or more results/ directories (each must contain "
        "per_trial.csv and traces.jsonl)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("lib/agent-eval-core/data/failure_fixtures.yaml"),
        help="output YAML path",
    )
    args = p.parse_args()

    task_index = _index_tasks()

    fixtures: list[dict[str, Any]] = []
    for results_dir in args.results_dirs:
        csv_path = results_dir / "per_trial.csv"
        trace_path = results_dir / "traces.jsonl"
        if not csv_path.exists():
            print(f"  skip {results_dir} (no per_trial.csv)", file=sys.stderr)
            continue

        print(f"reading {results_dir}", file=sys.stderr)
        with csv_path.open() as f:
            rows = list(csv.DictReader(f))

        spans = _load_spans(trace_path) if trace_path.exists() else []

        for row in rows:
            if row.get("passed") != "0":
                continue

            # Lookup task by instance_id.
            task = task_index.get(row["task_id"])

            # Find this trial's span (if traces exist) and classify.
            mode: str | None = None
            submitted: list[str] = []
            backend = ""

            trial_sp = None
            if spans:
                trial_sp = _find_trial_span(
                    spans,
                    task_id=row["task_id"],
                    condition=row["condition"],
                    model=row["model"],
                    replicate=int(row.get("replicate") or 0),
                )
            if trial_sp is not None:
                try:
                    mode = classify_trace(spans, trial_span_id=trial_sp["span_id"])
                except Exception as e:  # noqa: BLE001
                    print(
                        f"  classify_trace error on {row['task_id']}/{row['condition']}: {e}",
                        file=sys.stderr,
                    )
                submitted = _submitted_from_trial(spans, trial_sp)

            # CSV column fallback: one-shot and CLI trials don't emit
            # `done` tool_call spans, but their trial-level RunRecord
            # records `submitted` in the extra dict (now serialized to
            # the CSV).
            if not submitted and row.get("submitted"):
                try:
                    parsed = json.loads(row["submitted"])
                    if isinstance(parsed, list):
                        submitted = [str(p) for p in parsed]
                except (ValueError, TypeError):
                    pass

            # Fallback: the CSV column carries the trial-time
            # `failure_mode` extra dict entry (when available, requires
            # rerunning the sweep with the classifier wired in).
            mode = mode or (row.get("failure_mode") or None)

            # For the backend, prefer the per-turn span attribute via the
            # trial's children, falling back to the trial's `backend`.
            if trial_sp is not None:
                for ch in spans:
                    if ch.get("parent_span_id") == trial_sp["span_id"] and ch["name"] == "turn":
                        backend = ch.get("attrs", {}).get("agent_eval.backend", "")
                        if backend:
                            break

            fixtures.append(
                _format_entry(
                    row=row,
                    task=task,
                    failure_mode=mode,
                    submitted=submitted,  # not in CSV; left empty
                    backend=backend,
                    source_run=str(results_dir),
                )
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "# Failure fixtures — observed failures from this repo's runs.\n"
        "# See `lib/agent-eval-core/FAILURE_MODES.md` for the taxonomy.\n"
        "# Each entry is one observed failure case; downstream tests\n"
        "# can run their agent on `task` and check (a) does it succeed,\n"
        "# (b) does it exhibit the same `failure_mode`?\n\n"
        + yaml.safe_dump(fixtures, sort_keys=False, default_flow_style=False, width=120),
        encoding="utf-8",
    )
    print(f"\nwrote {len(fixtures)} fixture(s) to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
