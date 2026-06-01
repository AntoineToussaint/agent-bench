"""Project a SessionTrace into OpenInference OTLP/JSON.

This is the *interchange* layer of the two-layer trace stack (see TRACE.md →
"Relation to Mind / OpenInference"). `SessionTrace` is the rich native source
of truth; this emits the lossy OpenInference projection that agent-aware viewers
ingest — specifically Mind's agent-debugger and Arize Phoenix.

The output matches the OTLP/JSON span shape Mind's
`phoenix-probe/codex_to_otlp_files.py` writes and its `agent-debugger` ingests,
so a projected SessionTrace drops straight into that viewer. We use
OpenInference (not raw OTEL GenAI) because it has agent span kinds (AGENT,
EVALUATOR) and a `container.type` taxonomy (task/plan/objective/turn) that OTEL
GenAI lacks.

Mapping (our model -> OpenInference):
    SessionTrace root (__root__)  -> CHAIN span, container.type=task
    PhaseNode                     -> AGENT span, container.type=objective,
                                     objective.type=<phase>, llm.model_name=<model>
    PhaseReward                   -> child EVALUATOR span (eval.score / reward.kind)
    parent_id                     -> parentSpanId (fork = sibling AGENT spans)

What's lost in projection (kept only in the native SessionTrace): the restorable
Snapshot (conversation + env_ref) and the fork-as-RL-reset semantics. OTEL /
OpenInference model one execution's causality, not branchable state — exactly
why the native object is the source of truth.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval.trace import SessionTrace

_OI_KIND = "openinference.span.kind"


def _attr_value(v: Any) -> dict[str, Any]:
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}  # OTLP encodes ints as strings
    if isinstance(v, float):
        return {"doubleValue": v}
    return {"stringValue": v if isinstance(v, str) else str(v)}


def _attrs_list(d: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": k, "value": _attr_value(v)} for k, v in d.items() if v not in (None, "")]


def _span(
    trace_id: str,
    span_id: str,
    name: str,
    kind: str,
    start_ns: int,
    end_ns: int,
    parent: str | None,
    attrs: dict[str, Any],
) -> dict[str, Any]:
    a = dict(attrs)
    a[_OI_KIND] = kind
    s: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": "SPAN_KIND_INTERNAL",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": _attrs_list(a),
        "status": {"code": 0},
    }
    if parent:
        s["parentSpanId"] = parent
    return s


def session_to_otlp(
    trace: SessionTrace,
    *,
    run_name: str | None = None,
    scope_name: str = "agent-bench",
) -> list[dict[str, Any]]:
    """Project a SessionTrace into an OTLP/JSON document (list form).

    Times are synthesized monotonically from node order (the native trace
    carries no wall-clock — Date is deliberately avoided), so the projection is
    deterministic. Span ids reuse the native node ids (opaque strings; the
    viewer only uses them for parent linkage); the real OTEL span id, if the
    node carries one, is preserved in `agent_eval.otel.span_id`.
    """
    trace_id = trace.task_id or "session"
    spans: list[dict[str, Any]] = []

    for i, node in enumerate(trace):
        start = i * 1_000_000
        end = start + 1_000_000
        if node.phase == "__root__":
            attrs = {"container.type": "task", "session.id": trace.task_id}
            spans.append(_span(trace_id, node.id, trace.task_id, "CHAIN", start, end, None, attrs))
            continue

        attrs = {
            "container.type": "objective",
            "objective.type": node.phase,
            "llm.model_name": node.config.model,
            "prompt.id": node.config.prompt_id,
            "context.strategy": node.config.context_strategy,
        }
        if node.span_id:
            attrs["agent_eval.otel.span_id"] = node.span_id
        spans.append(
            _span(trace_id, node.id, node.phase, "AGENT", start, end, node.parent_id, attrs)
        )

        # Reward -> child EVALUATOR span (OpenInference has an EVALUATOR kind).
        if node.reward is not None:
            r_attrs = {
                "container.type": "objective",
                "eval.name": "phase_reward",
                "eval.score": node.reward.value,
                "reward.kind": node.reward.kind,
            }
            spans.append(
                _span(
                    trace_id,
                    f"{node.id}::reward",
                    f"reward:{node.phase}",
                    "EVALUATOR",
                    start,
                    end,
                    node.id,
                    r_attrs,
                )
            )

    return [
        {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": _attrs_list(
                            {
                                "service.name": "agent-bench",
                                "session.id": trace.task_id,
                                "run.name": run_name or trace.task_id,
                            }
                        )
                    },
                    "scopeSpans": [
                        {"scope": {"name": scope_name, "version": "0.1"}, "spans": spans}
                    ],
                }
            ]
        }
    ]


def write_otlp(
    trace: SessionTrace,
    path: Path | str,
    *,
    run_name: str | None = None,
) -> Path:
    """Write the OpenInference OTLP/JSON projection to `path`.

    Drop the file into a viewer's trace dir (e.g. Mind agent-debugger's
    `data/traces/` or `~/.mind/traces/<id>.json`) to inspect the run.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session_to_otlp(trace, run_name=run_name), indent=2))
    return path


__all__ = ["session_to_otlp", "write_otlp"]
