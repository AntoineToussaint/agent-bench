"""OpenTelemetry instrumentation for sweeps, trials, and tool calls.

Why this exists
---------------
Diagnosing a failed trial used to require: read stdout to find the right
trial → ls transcripts/ → write a one-off pretty-printer. Painful, and the
script never carried over to the next investigation.

With OTEL spans we get for free:
  - Parent/child structure (sweep > trial > turn > tool_call / llm_request)
  - Standard attribute names that downstream tools (Honeycomb, Jaeger,
    LangSmith) understand without custom adapters
  - Searchable / filterable timeline view of one or many runs

Standard
--------
We follow the **OpenTelemetry GenAI semantic conventions** for LLM-call
attributes (`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.*`).
Per-experiment custom attributes use the `agent_eval.*` namespace.

Exporter
--------
Default exporter is JSONL — one span per line to a local file. No backend
required. To send to Honeycomb / Jaeger / etc., point OTEL_EXPORTER_OTLP_*
env vars at the collector before calling `setup_tracing(otlp=True)`.

Usage
-----
    from agent_eval.tracing import setup_tracing, span_trial, span_turn

    setup_tracing(out_path="results/foo/traces.jsonl")

    with span_trial(task_id="t1", condition="turn-loop", model="haiku", replicate=0) as sp:
        for i in range(turns):
            with span_turn(turn_idx=i, backend="native") as turn_sp:
                ...

If `setup_tracing` is never called the spans are no-ops (zero cost) — so
trial code can use the span helpers unconditionally.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)


_SERVICE_NAME = "agent-bench"


# ============ JSONL exporter ============


class JsonlSpanExporter(SpanExporter):
    """Write each span as one line of JSON.

    Format is hand-rolled (not OTLP) — easier to read with `jq`, no
    protobuf, no collector. Maps directly to OTEL's data model.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate on init; one run = one file.
        self.fh = open(path, "w")

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        for sp in spans:
            ctx = sp.get_span_context()
            parent = sp.parent
            obj = {
                "name": sp.name,
                "trace_id": format(ctx.trace_id, "032x"),
                "span_id": format(ctx.span_id, "016x"),
                "parent_span_id": format(parent.span_id, "016x") if parent else None,
                "start_unix_ns": sp.start_time,
                "end_unix_ns": sp.end_time,
                "duration_ms": (sp.end_time - sp.start_time) / 1e6 if sp.end_time and sp.start_time else 0,
                "status": sp.status.status_code.name,
                "attrs": _coerce(dict(sp.attributes or {})),
                "events": [
                    {
                        "name": e.name,
                        "ts_unix_ns": e.timestamp,
                        "attrs": _coerce(dict(e.attributes or {})),
                    }
                    for e in sp.events
                ],
            }
            self.fh.write(json.dumps(obj) + "\n")
        self.fh.flush()
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        try:
            self.fh.close()
        except Exception:  # noqa: BLE001
            pass


def _coerce(attrs: dict[str, Any]) -> dict[str, Any]:
    """OTEL attrs can be primitive or homogeneous sequences. Coerce to JSON."""
    out: dict[str, Any] = {}
    for k, v in attrs.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            try:
                out[k] = json.dumps(v, default=str)
            except (TypeError, ValueError):
                out[k] = str(v)
    return out


# ============ setup ============


_provider: TracerProvider | None = None


def setup_tracing(
    out_path: Path | str | None = None,
    *,
    otlp: bool = False,
    service_name: str = _SERVICE_NAME,
) -> None:
    """Initialize a global TracerProvider.

    Args:
        out_path: file path for the JSONL exporter. If None and otlp is
            False, no exporter is attached (spans become no-ops).
        otlp: also wire an OTLP exporter via env vars
            (OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_EXPORTER_OTLP_HEADERS).
        service_name: resource attribute for `service.name`.

    Safe to call multiple times; later calls replace the provider.
    """
    global _provider
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if out_path is not None:
        # SimpleSpanProcessor flushes immediately — what we want for
        # research runs where the process exits and we don't want to
        # lose the last batch.
        provider.add_span_processor(
            SimpleSpanProcessor(JsonlSpanExporter(Path(out_path)))
        )

    if otlp:
        # Lazy import so users without otlp installed aren't penalized.
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))

    trace.set_tracer_provider(provider)
    _provider = provider


def shutdown_tracing() -> None:
    """Flush + close. Idempotent."""
    if _provider is not None:
        _provider.shutdown()


def _tracer() -> trace.Tracer:
    return trace.get_tracer(_SERVICE_NAME)


# ============ span helpers ============
#
# Thin wrappers around start_as_current_span that set the attributes
# we want consistently. Trial code calls these; it never touches OTEL
# directly. That way if we swap exporters or attribute names later,
# the experiment code doesn't change.


@contextmanager
def span_sweep(
    n_models: int,
    n_conditions: int,
    n_tasks: int,
    repetitions: int,
) -> Iterator[trace.Span]:
    """Root span — one per sweep run."""
    with _tracer().start_as_current_span("sweep") as sp:
        sp.set_attribute("agent_eval.sweep.n_models", n_models)
        sp.set_attribute("agent_eval.sweep.n_conditions", n_conditions)
        sp.set_attribute("agent_eval.sweep.n_tasks", n_tasks)
        sp.set_attribute("agent_eval.sweep.repetitions", repetitions)
        sp.set_attribute(
            "agent_eval.sweep.n_trials",
            n_models * n_conditions * n_tasks * repetitions,
        )
        yield sp


@contextmanager
def span_trial(
    task_id: str,
    condition: str,
    model: str,
    replicate: int,
) -> Iterator[trace.Span]:
    """One span per trial. Caller sets pass/fail attrs at the end."""
    with _tracer().start_as_current_span("trial") as sp:
        sp.set_attribute("agent_eval.task.id", task_id)
        sp.set_attribute("agent_eval.condition", condition)
        sp.set_attribute("gen_ai.request.model", model)
        sp.set_attribute("agent_eval.replicate", replicate)
        yield sp


@contextmanager
def span_turn(
    turn_idx: int,
    backend: str,
) -> Iterator[trace.Span]:
    """One span per loop turn. Caller adds per-turn attrs (tool counts, tokens)."""
    with _tracer().start_as_current_span("turn") as sp:
        sp.set_attribute("agent_eval.turn.idx", turn_idx)
        sp.set_attribute("agent_eval.backend", backend)
        yield sp


@contextmanager
def span_llm_request(
    model: str,
    backend: str,
    operation: str = "chat",
) -> Iterator[trace.Span]:
    """One span per LLM API call.

    Follows OTEL GenAI semantic conventions for `gen_ai.*` attrs so any
    OTEL-aware backend (Honeycomb, LangSmith, OpenLLMetry) treats this
    span as an LLM call without custom config.
    """
    with _tracer().start_as_current_span("llm.request") as sp:
        sp.set_attribute("gen_ai.system", _infer_system(model))
        sp.set_attribute("gen_ai.request.model", model)
        sp.set_attribute("gen_ai.operation.name", operation)
        sp.set_attribute("agent_eval.backend", backend)
        yield sp


def record_llm_usage(
    sp: trace.Span,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> None:
    """Attach OTEL GenAI usage attrs to an llm.request span."""
    sp.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    sp.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    sp.set_attribute("agent_eval.usage.cache_read_tokens", cache_read_tokens)
    sp.set_attribute("agent_eval.usage.cache_creation_tokens", cache_creation_tokens)


@contextmanager
def span_tool_call(name: str, args: dict[str, Any]) -> Iterator[trace.Span]:
    """One span per dispatched tool call against the repo / environment.

    NOT to be confused with `span_llm_request` — that wraps the model
    API call. This wraps the *application's* execution of a tool the
    model asked for.
    """
    with _tracer().start_as_current_span("tool_call") as sp:
        sp.set_attribute("agent_eval.tool.name", name)
        # Truncate huge args (file contents, regex patterns) at the boundary
        # so traces stay readable.
        sp.set_attribute("agent_eval.tool.args", json.dumps(args, default=str)[:1000])
        yield sp


def _infer_system(model: str) -> str:
    m = model.lower()
    if "claude" in m or "anthropic" in m:
        return "anthropic"
    if "gpt" in m or m.startswith("o1") or m.startswith("o3") or "openai" in m:
        return "openai"
    return "unknown"
