"""Per-trial transcript JSON dump + inspection helpers.

Trials produce a `Transcript` (the in-memory log of system + user + assistant
turns) and a `RunRecord` (the structural summary). This module persists the
former to disk and reads it back for inspection.

File layout: one JSON file per trial at
    <out_dir>/<task_id>__<model>__<condition>.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval.types import RunRecord, Transcript


def dump_transcript(
    out_dir: Path,
    record: RunRecord,
    transcript: Transcript,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write the transcript to `<out_dir>/<task>__<model>__<condition>.json`.

    Returns the path. Also useful to assign to `record.transcript_path` if the
    caller wants the RunRecord to reference its transcript.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_task = record.task_id.replace("/", "__")
    path = out_dir / f"{safe_task}__{record.model}__{record.condition}.json"
    payload = {
        "task_id": record.task_id,
        "model": record.model,
        "condition": record.condition,
        "replicate": record.replicate,
        "passed": record.passed,
        "turns": record.turns,
        "tool_calls": record.tool_calls,
        "invalid_tool_calls": record.invalid_tool_calls,
        "usage": record.usage.__dict__,
        "cost_usd": record.cost_usd,
        "latency_seconds": record.latency_seconds,
        "error": record.error,
        "system": transcript.system,
        "entries": transcript.entries,
        **(extra or {}),
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def load_transcript(path: Path) -> dict[str, Any]:
    """Read a transcript JSON back into a dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def summarize_transcript(data: dict[str, Any], max_content: int = 200) -> str:
    """Quick human-readable summary of one transcript JSON.

    Returns a multi-line string with one line per conversation entry.
    Tool calls are rendered as `CALL name(args...)`; tool results as
    `OK content` or `ERROR content`.
    """
    lines = [
        f"task: {data.get('task_id')} | model: {data.get('model')} | "
        f"condition: {data.get('condition')}",
        f"passed: {data.get('passed')} | cost: ${data.get('cost_usd', 0):.4f} | "
        f"turns: {data.get('turns')} | latency: {data.get('latency_seconds', 0):.2f}s",
        f"entries: {len(data.get('entries') or [])}",
        "",
    ]
    for i, e in enumerate(data.get("entries") or []):
        role = e.get("role")
        if role == "user":
            text = str(e.get("content") or "")[:max_content].replace("\n", " / ")
            lines.append(f"[{i:2}] USER     {text!r}")
        elif role == "assistant":
            if e.get("text"):
                snip = e["text"][:max_content].replace("\n", " / ")
                lines.append(f"[{i:2}] ASST_TXT {snip!r}")
            for tc in e.get("tool_calls", []):
                args_str = json.dumps(tc["arguments"])[:max_content].replace("\n", " / ")
                lines.append(f"[{i:2}] CALL     {tc['name']}({args_str})")
        elif role == "tool":
            for r in e.get("results", []):
                content = r["content"][:max_content].replace("\n", " / ")
                lines.append(f"[{i:2}] {r['status'].upper():5}    {content}")
    return "\n".join(lines)
