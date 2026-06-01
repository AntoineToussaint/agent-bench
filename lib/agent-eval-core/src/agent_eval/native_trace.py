"""Project a SessionTrace into Mind's native `execution.json` shape (partial).

Where `openinference.py` emits the *skeleton* (span tree → timing/model/reward),
this emits the *body* that lights up Mind agent-debugger's native panels:
objectives, per-LLM-call records, tool calls, timeline, and an object index that
links native objects back to the OpenInference spans.

It is deliberately PARTIAL and honest. Mind's `NativeTraceDocument`
(agent-debugger/src/types/native-trace.ts) is fully-optional and open
(`NativeRecord = Record<string, unknown>`), so the viewer renders what's present
and ignores what's absent. We populate only what a SessionTrace + its captured
`Transcript` genuinely contain:

  populated:  task, plan + objectives (one per phase), audit.llm_calls (model,
              system prompt, raw reasoning text, tool_call_count, usage),
              tool_calls, timeline, object_index, run.summary counts.
  ABSENT (do not fabricate): context_frames + omission_count, prompt profiles
              (id/version/system_hash), structured audit next_action / plan
              mutations, artifacts. These are the context-engineering signals
              STRATEGY.md will instrument for Step 2 — they flow in here as we
              start recording them, not before.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval.trace import PhaseNode, SessionTrace


def _status_of(node: PhaseNode) -> str:
    if node.reward is None:
        return "unknown"
    if node.reward.detail.get("passed") is True or node.reward.value >= 1.0:
        return "achieved"
    return "failed"


def _calls_from_phase(node: PhaseNode) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reconstruct (llm_calls, tool_calls) from a phase's captured conversation.

    The Transcript entries are the source: assistant entries become LLM audit
    records (one per turn); their tool_calls become tool records.
    """
    llm_calls: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    conv = node.snapshot.conversation
    if conv is None:
        return llm_calls, tool_calls
    system = conv.system
    turn = 0
    for entry in conv.entries:
        if entry.get("role") != "assistant":
            continue
        turn += 1
        tcs = entry.get("tool_calls", []) or []
        llm_calls.append(
            {
                "objective_id": node.id,
                "turn": turn,
                "model": node.config.model,
                "model_ref": node.config.model,
                "prompt": {"system": system, "profile_id": node.config.prompt_id},
                "response": {
                    "reasoning": entry.get("text", "") or "",
                    "tool_call_count": len(tcs),
                },
                "usage": entry.get("usage", {}) or {},
            }
        )
        for tc in tcs:
            tool_calls.append(
                {
                    "objective_id": node.id,
                    "turn": turn,
                    "name": tc.get("name"),
                    "arguments": tc.get("arguments", {}),
                }
            )
    return llm_calls, tool_calls


def session_to_native(trace: SessionTrace, *, run_name: str | None = None) -> dict[str, Any]:
    """Build a partial NativeTraceDocument for Mind's agent-debugger."""
    phases = [n for n in trace if n.phase != "__root__"]

    objectives: dict[str, dict[str, Any]] = {}
    all_llm: list[dict[str, Any]] = []
    all_tools: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    object_index: list[dict[str, Any]] = []

    for i, node in enumerate(phases):
        llm_calls, tool_calls = _calls_from_phase(node)
        all_llm.extend(llm_calls)
        all_tools.extend(tool_calls)

        objectives[node.id] = {
            "ID": node.id,
            "Type": node.phase,
            "Brief": f"{node.phase} ({node.config.model})",
            "Status": _status_of(node),
            "Attempts": 1,
            "ParentID": node.parent_id,
        }
        # object_index ties the native objective to its OpenInference span
        # (we use node.id as the span id in the projection too).
        object_index.append(
            {
                "id": node.id,
                "kind": "objective",
                "parent_id": node.parent_id,
                "native_id": node.id,
                "span_id": node.id,
                "display_name": node.phase,
                "metadata": {
                    "reward": node.reward.value if node.reward else None,
                    "reward_kind": node.reward.kind if node.reward else None,
                },
            }
        )
        timeline.append(
            {"index": i, "kind": "objective", "objective_id": node.id, "phase": node.phase}
        )

    # Terminal outcome: achieved if any phase achieved (single-phase today).
    statuses = [o["Status"] for o in objectives.values()]
    terminal = "achieved" if "achieved" in statuses else ("failed" if statuses else "unknown")

    return {
        "version": 1,
        "run": {
            "version": 1,
            "run_name": run_name or trace.task_id,
            "summary": {
                "objectives": list(objectives.values()),
                "llm_port_calls": len(all_llm),
                "tool_calls": len(all_tools),
                "context_frames": 0,  # not yet instrumented
                "artifact_count": 0,
            },
        },
        "task": {
            "ID": trace.task_id,
            "Status": terminal,
            "TerminalOutcome": terminal,
            "Plan": {"TaskID": trace.task_id, "Objectives": objectives},
        },
        "audit": {"version": 1, "llm_calls": all_llm, "tool_calls": all_tools},
        "llm_port_calls": all_llm,
        "tool_calls": all_tools,
        "timeline": timeline,
        "object_index": object_index,
    }


def write_native(trace: SessionTrace, path: Path | str, *, run_name: str | None = None) -> Path:
    """Write the partial `execution.json` to `path`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session_to_native(trace, run_name=run_name), indent=2))
    return path


__all__ = ["session_to_native", "write_native"]
