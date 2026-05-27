"""Render a sweep's OTEL trace file as a readable per-trial timeline.

Usage:
    uv run --package file-localization python \
        experiments/file-localization/scripts/show_traces.py \
        results/<out_dir>/traces.jsonl

    # Filter to one condition:
    ... show_traces.py results/.../traces.jsonl --condition turn-loop-schema

    # Filter to one task:
    ... show_traces.py results/.../traces.jsonl --task astropy__astropy-12907

    # Show only failed trials:
    ... show_traces.py results/.../traces.jsonl --failed

The output is text — one block per trial — with the turn timeline,
tool calls per turn, token deltas, and the trial's pass/fail. The
trace JSONL is the source of truth; the markdown summary, transcripts,
and this viewer are all derived from it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_spans(path: Path) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                spans.append(json.loads(line))
    return spans


def index_by_parent(spans: list[dict[str, Any]]) -> dict[str | None, list[dict[str, Any]]]:
    """Group spans by their parent_span_id (None for root spans)."""
    out: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for sp in spans:
        out[sp.get("parent_span_id")].append(sp)
    # Sort children by start time so the rendering is chronological.
    for k in out:
        out[k].sort(key=lambda s: s["start_unix_ns"])
    return out


def render_trial(
    trial_sp: dict[str, Any],
    by_parent: dict[str | None, list[dict[str, Any]]],
    all_spans: list[dict[str, Any]],
) -> str:
    attrs = trial_sp.get("attrs", {})
    lines: list[str] = []
    passed = attrs.get("agent_eval.trial.passed")
    status_icon = "✓" if passed else "✗"
    err = attrs.get("agent_eval.trial.error", "")
    # Classifier output, when applicable. Surface it inline so the
    # viewer tells you WHY a trial failed without reading transcripts.
    from agent_eval.failure_modes import classify_trace as _ct

    try:
        mode = _ct(all_spans, trial_span_id=trial_sp["span_id"])
    except Exception:  # noqa: BLE001
        mode = None
    lines.append(
        f"\n{status_icon} TRIAL  task={attrs.get('agent_eval.task.id')}  "
        f"condition={attrs.get('agent_eval.condition')}  "
        f"model={attrs.get('gen_ai.request.model')}  "
        f"rep={attrs.get('agent_eval.replicate')}  "
        f"turns={attrs.get('agent_eval.trial.turns')}  "
        f"tool_calls={attrs.get('agent_eval.trial.tool_calls')}  "
        f"cost=${attrs.get('agent_eval.trial.cost_usd', 0):.4f}  "
        f"latency={attrs.get('agent_eval.trial.latency_seconds', 0):.1f}s"
        + (f"  MODE={mode}" if mode else "")
        + (f"  ERR={err}" if err else "")
    )
    span_id = trial_sp["span_id"]
    turns = by_parent.get(span_id, [])
    if not turns:
        lines.append("  (no turns recorded)")
        return "\n".join(lines)

    # Headers — printed once per trial.
    lines.append(
        "  turn  | actions                                              | in_tok | out_tok | new_sig | outcome    | dur"
    )
    lines.append(
        "  ------+------------------------------------------------------+--------+---------+---------+------------+------"
    )
    for turn_sp in turns:
        ta = turn_sp.get("attrs", {})
        idx = ta.get("agent_eval.turn.idx")
        names_json = ta.get("agent_eval.turn.tool_names", "[]")
        try:
            names = json.loads(names_json) if isinstance(names_json, str) else names_json
        except Exception:  # noqa: BLE001
            names = []
        names_str = ", ".join(names) if names else "(none)"
        if len(names_str) > 52:
            names_str = names_str[:49] + "..."
        in_tok = ta.get("gen_ai.usage.input_tokens", 0)
        out_tok = ta.get("gen_ai.usage.output_tokens", 0)
        new_sig = ta.get("agent_eval.turn.added_new_signature")
        new_str = "yes" if new_sig else ("no" if new_sig is False else "—")
        outcome = ta.get("agent_eval.turn.outcome", "—")
        if ta.get("agent_eval.turn.forced_terminal"):
            outcome = "FORCED " + outcome
        dur = turn_sp.get("duration_ms", 0)
        lines.append(
            f"  {idx:>4}  | {names_str:<52} | {in_tok:>6} | {out_tok:>7} | {new_str:>7} | {outcome:<10} | {dur:.0f}ms"
        )

        # Per-turn tool_call details (nested, indented).
        tool_calls = by_parent.get(turn_sp["span_id"], [])
        tool_calls = [t for t in tool_calls if t["name"] == "tool_call"]
        for tc in tool_calls:
            ta2 = tc.get("attrs", {})
            args_str = ta2.get("agent_eval.tool.args", "")
            if len(args_str) > 80:
                args_str = args_str[:77] + "..."
            result_n = ta2.get("agent_eval.tool.result_chars", 0)
            status = ta2.get("agent_eval.tool.status", "?")
            lines.append(
                f"        └─ {ta2.get('agent_eval.tool.name'):<10} {args_str:<80} → {status} ({result_n}ch)"
            )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="path to a traces.jsonl file")
    parser.add_argument("--task", help="filter by task id substring")
    parser.add_argument("--condition", help="filter by condition substring")
    parser.add_argument("--model", help="filter by model substring")
    parser.add_argument("--failed", action="store_true", help="only show failed trials")
    parser.add_argument("--passed", action="store_true", help="only show passed trials")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"trace file not found: {args.path}", file=sys.stderr)
        return 2

    spans = load_spans(args.path)
    by_parent = index_by_parent(spans)

    # Trial spans are children of the sweep span (or rootless).
    trial_spans = [s for s in spans if s["name"] == "trial"]
    trial_spans.sort(key=lambda s: s["start_unix_ns"])

    matched = 0
    for ts in trial_spans:
        attrs = ts.get("attrs", {})
        if args.task and args.task not in (attrs.get("agent_eval.task.id") or ""):
            continue
        if args.condition and args.condition not in (attrs.get("agent_eval.condition") or ""):
            continue
        if args.model and args.model not in (attrs.get("gen_ai.request.model") or ""):
            continue
        passed = attrs.get("agent_eval.trial.passed")
        if args.failed and passed:
            continue
        if args.passed and not passed:
            continue
        print(render_trial(ts, by_parent, spans))
        matched += 1

    if matched == 0:
        print("(no trials matched filters)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
