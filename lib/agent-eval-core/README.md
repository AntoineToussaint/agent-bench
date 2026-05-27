# agent-eval-core

The plumbing shared by every experiment under `experiments/`. Domain-agnostic.

It answers four questions an LLM-agent benchmark always asks:

1. **Which model and protocol am I running?** → `ModelHandle` (a `ModelClient` paired with a `ToolBackend`).
2. **How do I drive a sweep across models × conditions × tasks?** → `Sweep`.
3. **How do I record what happened?** → `RunRecord` + OTEL spans + JSONL transcripts.
4. **What broke and why?** → `failure_modes.classify_output / classify_trace`.

Experiments contribute their own task / scoring / trial functions and plug into this surface.

## What's inside

```
src/agent_eval/
  types.py              # ToolCall, ToolResult, AssistantMessage, ModelClient,
                        # ModelHandle, RunRecord, Transcript, TurnUsage
  models/
    __init__.py         # make_client(name), make_model(name, backend=?)
    anthropic_client.py # Anthropic Messages API; supports tool_choice
    openai_client.py    # OpenAI Chat Completions; Anthropic-shape tools converted
    openrouter_client.py
    registry.py         # YAML-driven default-backend-per-model lookup
  protocols/
    types.py            # ToolSpec, ToolBackend protocol, ActionResponse
    native.py           # NativeToolUseBackend  — provider tool_use, tool_choice=auto
    schema.py           # SchemaEnforcedBackend — provider tool_use, tool_choice=any
    prompt_json.py      # PromptJSONBackend     — text-only fenced JSON + mimicry detection
  sweep/
    runner.py           # Sweep grid runner; opens span_sweep + span_trial
    budget.py           # cumulative $ cap with hard-stop
  tracing.py            # OpenTelemetry GenAI-conventions instrumentation;
                        # JSONL exporter; span_trial / span_turn /
                        # span_llm_request / span_tool_call helpers
  reports.py            # write_csv, write_aggregate_csv, write_markdown
  pricing.py            # YAML-driven per-model cost lookup
  transcripts.py        # dump / load / summarize structured trial transcripts
  failure_modes.py      # classify_output, classify_trace (see FAILURE_MODES.md)
  data/
    pricing.yaml             # per-model token costs
    model_backends.yaml      # per-model default backend (empirical)
    failure_fixtures.yaml    # observed failure cases for downstream testing
```

## Trial contract

Every experiment implements:

```python
def trial(handle: ModelHandle, condition: str, task: TaskT) -> RunRecord: ...
```

- `handle.client` is the LLM API client (Anthropic / OpenAI / OpenRouter).
- `handle.backend` is the wire protocol (Native / Schema / PromptJSON). The trial calls `handle.backend.request(handle.client, tool_specs)` rather than `handle.client.step(...)` directly — so swapping protocols requires no trial-code change.
- `condition` is a free string used as a sweep dimension and a row label in reports.
- `task` is experiment-defined (`LocalizationTask`, `Task`, `TaskSpec`, …).
- `RunRecord` is the single normalized output: pass/fail, turns, tool calls, usage, cost, latency, optional extra dict.

Sweep usage:

```python
from agent_eval import Sweep
records = Sweep(
    models=["claude-haiku-4-5", "claude-sonnet-4-6"],
    conditions=["one-shot", "turn-loop"],
    tasks=my_tasks,
    trial=my_trial,
    repetitions=2,
).run()
```

The runner constructs a `ModelHandle` per cell via `make_model(name)` (using `data/model_backends.yaml` for the default backend) and passes it to `trial`. Research sweeps that want to compare backends pass `backend_for_condition=...` to override per condition.

## Tracing

`agent_eval.tracing.setup_tracing(out_path="traces.jsonl")` wires an exporter; spans then flow automatically as trials run. The default exporter writes one span per line of JSON — readable with `jq`, no collector required. Set `otlp=True` to additionally export over OTLP/HTTP.

Span tree per trial:

```
sweep
└── trial   (attrs: task_id, condition, model, replicate, passed, cost, turns)
    └── turn   (attrs: idx, backend, tool_names, n_actions, new_signature)
        ├── llm.request   (attrs: gen_ai.system, gen_ai.usage.*)
        └── tool_call     (attrs: tool.name, tool.args, tool.status)
```

One-shot trials skip the `turn` level — they're a single `llm.request` under `trial`.

## Failure-mode classification

`agent_eval.failure_modes.classify_output(...)` and `classify_trace(spans, trial_id)` diagnose failed trials into 10 named categories grouped in 3 tiers (information / process / protocol). See `FAILURE_MODES.md` for the taxonomy and citations.

The classifier output appears as a `failure_mode` column in `per_trial.csv` and a "Failure modes" section in `summary.md`. Trial functions that wire `classify_output(...)` into the record's `extra` dict get this for free.

## Adding a new model

1. Add the model id to the right `*_MODELS` dict in `models/anthropic_client.py` / `openai_client.py` / `openrouter_client.py`.
2. Add a row to `data/pricing.yaml` with input/output/cache rates.
3. Add a row to `data/model_backends.yaml` with the recommended backend (start with `native`; update after running the comparison sweep).
4. Run any experiment with `--model <id>` — no other code changes needed.

## Adding a new backend

1. Add a module under `protocols/` implementing the `ToolBackend` protocol from `protocols/types.py`.
2. Register the short name in `models/registry.py` (`_BACKEND_FACTORIES`).
3. Reference it in `data/model_backends.yaml` for any model that should default to it.

## Test layout

`tests/` covers: `Sweep` grid + budget enforcement, `reports.write_csv` + markdown, `Transcript` round-trip, and a smoke test of the `failure_modes` classifier with synthetic input. Real-LLM smoke tests live in each experiment's `scripts/`.
