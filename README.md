# agent-bench

Research monorepo: agent + LLM evaluation experiments, sharing a domain-agnostic eval library.

## Layout

```
agent-bench/
  lib/
    agent-eval-core/         # the shared library: model clients, sweep
                             # runner, budget, pricing, transcripts, reports.
                             # Domain-agnostic — knows nothing about formats /
                             # tools / retrievers.
  experiments/
    code-editing/            # code-edit formats × protocols × models
    tool-selection/          # tool-catalog selection strategies × phases
    file-localization/       # SWE-bench file localization
  notes/                     # cross-experiment findings, synthesis writeups
```

Each experiment is an independent uv package; they all depend on `agent-eval-core`
as a workspace member.

## Quickstart

```bash
git clone git@github.com:AntoineToussaint/agent-bench.git
cd agent-bench
cp .env.example .env       # ANTHROPIC_API_KEY, OPENAI_API_KEY
uv sync                    # installs lib + all experiments

# run an experiment's CLI
uv run --package code-editing code-editing list-models
uv run --package code-editing code-editing list-formats

# run an experiment's tests
uv run --package code-editing pytest experiments/code-editing/tests/ -q
uv run --package agent-eval-core pytest lib/agent-eval-core/tests/ -q
```

## What's in each experiment

| Experiment | Question | Headline finding |
|---|---|---|
| `code-editing` | How should LLMs express code edits? Text replacement, unified diff, semantic ops, or a hybrid — and via tool_use, structured text output, or agent loop? | Single-shot tool_use has a "~1 call per response" ceiling. Structured JSON output lifts Sonnet 4.6 from 57% → 100% on 14 medium tasks. **The protocol is more important than the format**, and more important than the model below Opus. |
| `tool-selection` | How should LLMs *find* the right tool out of a large catalog? Full surfacing vs filtered (BM25, embeddings, LLM router) × phase architectures. | Two-phase tool calling (cheap classifier + smart generator) scales nearly flat with catalog size; one-phase scales linearly worse. At 150 tools, 2phase-Haiku is **4× cheaper per success** than 1phase-Haiku and 31× cheaper than 1phase-Sonnet. |
| `file-localization` | Can retrievers find the files an issue needs edited? Tests `recall@k` and `NDCG@k` on SWE-Bench gold patches. | (in progress) |

Both `code-editing` and `tool-selection` independently observe **the Sonnet 4.6 one-call regression** ([anthropic-sdk-typescript#956](https://github.com/anthropics/anthropic-sdk-typescript/issues/956)). The generic conclusion is written up in [`notes/tool-use-vs-structured-output.md`](notes/tool-use-vs-structured-output.md): the canonical `tool_use` API is the wrong shape on two production scaling axes (many tools, multi-step plans), and both workarounds (two-phase selection, structured text output) bypass the API rather than fight it.

## Library: `agent-eval-core`

What you bring: a `trial = (model_client, condition_str, task) -> RunRecord` function.
What the library handles: model registry, sweep iteration, parallelism, budget cap,
pricing ($/Mtok with Jan 2026 prices), CSV/markdown reports, per-trial transcript dumps.

```python
from agent_eval import Sweep, make_client, RunRecord

def my_trial(client, condition, task):
    ...
    return RunRecord(...)

records = Sweep(
    models=["claude-haiku-4-5", "claude-sonnet-4-6"],
    conditions=["protocol_a", "protocol_b"],
    tasks=my_tasks,
    trial=my_trial,
).run()
```

See [`lib/agent-eval-core/README.md`](lib/agent-eval-core/README.md) and
[`lib/agent-eval-core/examples/`](lib/agent-eval-core/examples/) for details.

## Why this exists

Most coding-agent benchmarks (SWE-Bench, Aider's polyglot, vendor evals)
hard-couple their measurement harness to one specific question. That makes it
hard to study orthogonal axes — protocol choice, format choice, selection
strategy, model choice — with the rest held constant.

This repo separates the *boring infrastructure* (sweep runner, budget, pricing,
reports) from the *experimental question* (what's a condition? what does a
trial mean?). Each experiment defines its own trial; the library handles the
rest. New experiments are ~1 day of domain code plus a few lines of glue.

## Status

Active research. v0.x — the library's API may shift; pin to a SHA if you depend
on it externally.
