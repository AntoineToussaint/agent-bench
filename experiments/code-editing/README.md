# code-editing

Comparison harness for **edit formats** — the structured surface an LLM uses to express code changes. Same task, same model, different format; does pass-rate change? cost? latency?

The research question: *for code editing specifically, does the wire format matter as much as the model?* (Aider's empirical answer: yes, a lot. We're replicating + extending.)

## What it tests

Each trial is one (task, model, format, mode) combination:

- **task** — a small Python or TypeScript fixture (~42 tasks under `tasks/`, organized by edit category: localized bug, multi-site change, cross-file rename, signature change, etc.)
- **model** — anything `agent_eval.make_client` knows about
- **format** — the edit surface; one of 4 below
- **mode** — single-shot, structured (JSON), or agent (turn-loop)

Pass criterion: an oracle command (`pytest`, `tsc`, …) returns exit 0 against the merged workdir + hidden test overlay. Format-quality and model-quality blur in real usage; the formats × tasks × oracles design isolates them.

## Edit formats

| name | shape | example |
|---|---|---|
| `search_replace` | single-string `old_str` / `new_str`; `old_str` must appear exactly once | classic Aider |
| `unified_diff` | multi-hunk diff blocks, context-anchored, multi-file | `git diff` shape |
| `semantic` | intent-named ops on a libcst CST (Python only): `rename`, `replace`, `change_value_of`, `add_parameter`, `add_import`, `create_file`, … | "AST as a tool surface" |
| `search_plus` | text-edit + semantic shortcuts in one hybrid format | the hybrid we built to test "what if you don't have to choose" |

Each format implements `EditFormat`: a `tools()` method returning JSON-Schema-shaped tool specs, an `apply(ToolCall, workdir) → ToolResult` executor, and a `system_prompt()` describing usage.

## Execution modes

The same (task, model, format) can be run three ways:

| mode | turns | model sees | use case |
|---|---|---|---|
| `single` | 1 | full project upfront, all edits in one response | isolates *format quality* from *agent navigation* |
| `structured` | 1 | full project upfront, emits one fenced JSON change-set as text (no tool_use API) | tests prompt-format fluency without provider tool-use rails |
| `agent` | up to 12 | iterative exploration via `view_file`/`list_files`, edits via the format's tools, terminates with `done` | what a real coding agent does |

`agent` is the canonical mode; `single` and `structured` are controls. Same scoring oracle for all three.

## Install

```bash
uv sync --package code-editing
```

For TypeScript tasks: `npm i -g typescript` (the oracle runs `tsc`).

## Usage

```bash
# List what's available
uv run code-editing list-formats
uv run code-editing list-tasks
uv run code-editing list-models

# One trial
uv run code-editing run \
  --task c01_localized_bug \
  --model claude-haiku-4-5 \
  --fmt search_replace \
  --mode agent

# Sweep
uv run code-editing sweep \
  --models claude-haiku-4-5,claude-sonnet-4-6 \
  --formats search_replace,unified_diff,semantic \
  --mode agent \
  --out results/sweep_haiku_sonnet
```

Each sweep writes `per_trial.csv`, `per_cell.csv`, `summary.md`, `traces.jsonl`, and `transcripts/*.json` to `--out`.

## What runs under the hood

The three runners — `run_trial` (agent), `run_structured` (one-shot JSON), `run_single_shot` (one-shot tool_use) — live in `src/code_editing/bench/runner.py`. They share an oracle-based scorer (`bench/oracle.py`) and a task materializer (`bench/task.py`) that copies fixtures into a tmp workdir before each run.

All three runners accept an optional `handle: ModelHandle` argument from `agent_eval`. When provided, the model call is routed through the handle's `ToolBackend` and OTEL spans (`span_trial → span_turn → span_llm_request + span_tool_call`) are emitted in the standard shape that `experiments/file-localization/scripts/show_traces.py` can render. When omitted, the legacy `client.step()` path is taken — preserving direct CLI use.

## Task layout

```
tasks/v2/
  _base/                     # shared fixtures
  c01_localized_bug/
    meta.yaml                # task spec (instructions, category, oracle_cmd)
    starter/                 # files the model gets to edit
    _overlay/                # hidden files merged before oracle runs (typically tests)
  c02_multi_site/
  ...
```

## Contract

Full Task / Result / scoring shape: `CONTRACT.md`. Source of truth: `src/code_editing/contract.py`.

## Tests

`tests/` covers: each format's `.apply()` semantics with handcrafted fixtures, the runner's escape valves (consecutive-error and no-progress aborts), oracle execution + workdir snapshotting. 54 tests, runs in ~7s.

## Patch Cascade (cost/latency study on this harness)

A study built on the same task + oracle machinery, asking a different question:
instead of one model solving the task, a **cheap model drafts a full patch and
stronger models each emit only a *correction* against the current state**, climbing
a model-tier ladder (haiku → sonnet → opus). The bet: output tokens dominate cost
and latency, so making the expensive model emit a short *diff* instead of a full
answer should buy its quality more cheaply. (It's a black-box, answer-level analog
of speculative decoding; the cascade + early-stop pieces are borrowed from
FrugalGPT, the diff-as-escalation is the new knob.)

| piece | where |
|---|---|
| cascade runner | `bench/runner.py::run_cascade` |
| run it | `scripts/run_patch_cascade.py` (`--dry-run`, `--sizes`, `--only`, `--reps`) |
| analysis | `scripts/analyze_diff_vs_rewrite.py`, `scripts/analyze_locality.py` |
| tests | `tests/test_patch_cascade.py` (offline, stub client) |

Design notes:
- **Caching / append-only.** Task + *original* files live in the cached `system`
  prefix; correction tiers append only a unified diff of the prior attempt, so the
  cached prefix stays byte-identical across same-model calls. (Caches are per-model,
  so different tiers of one cascade never share — the win is cross-condition / re-run.)
- **Early-stop gate** (`gate_client`): a cheap, deliberately *conservative* judge
  halts the ladder when confident. Deploy-honest — it never sees the oracle; its
  accuracy is scored against a hidden oracle probe (`gate_correct`, `first_passing_tier`).
- **diff vs rewrite ablation** (`correction_style="diff" | "rewrite"`): rewrite
  regenerates whole changed files (≈ a vanilla cascade); the diff/rewrite gap is the
  novel knob's actual contribution.

**Findings** (haiku-4-5 / sonnet-4-6 / opus-4-8, Jan-2026 prices):
- With prompt caching, the cascade **Pareto-beats single-shot Opus** on cost at equal
  pass; **warm-cache cost ≈ 2.7× cheaper than cold** (latency unchanged — caching
  speeds input, not generation).
- Whether the diff beats plain rewrite is governed by **edit *concentration*, not file
  size**: diff wins for substantial **localized** edits (`edit_fraction ≲ 0.5` →
  +7–30% cost, +7–45% latency, and more *reliable* on big files); it **loses** for
  **diffuse** many-hunk edits (`edit_fraction ≥ 1`, where per-hunk context overhead
  makes the diff bigger than a rewrite) and for trivial edits.
- **Latency benefits more than cost** where diff wins (output tokens dominate wall-clock).
  Decomposing latency into TTFT + generate (streaming, `TurnUsage.ttft_seconds` /
  `generate_seconds`) shows the cascade's extra wall-clock is **cumulative *decode*, not
  startups** — total TTFT across a 2-tier cascade ≈ a single Opus call's TTFT; the blow-up is
  summed generation. So caching can't help latency (it only speeds TTFT ≈15–20% of the total),
  and the lever is total tokens *generated*. Single-shot Opus stays latency-king on hard tasks.
- The conservative gate recovers early-stop savings without shipping broken drafts.
- Boundary: on *medium* tasks the effect is in the noise — outputs are too short for the
  diff to matter; the win shows up on large/localized edits.

This is a context/cost side-study, separate from the phased-agent platform in
`STRATEGY.md`. Natural follow-up: route diff-vs-rewrite per edit by *predicting*
`edit_fraction` from the cheap draft.

## See also

- `lib/agent-eval-core/README.md` — the shared library this experiment plugs into
- `lib/agent-eval-core/FAILURE_MODES.md` — failure-mode taxonomy applicable here too
- Aider's [edit format leaderboard](https://aider.chat/docs/leaderboards/edit.html) — the canonical prior art
