# agent-bench

A research bench for figuring out **how to build better coding agents** — and
the home of one specific bet about how to build them.

> **Coming back after a break? Read this page top to bottom, then
> [`STRATEGY.md`](lib/agent-eval-core/STRATEGY.md).** That's the whole
> orientation.

---

## What is this?

Two things in one repo:

1. **A measurement bench.** Infrastructure that separates the boring parts of
   running LLM/agent experiments (sweeps, budget, pricing, transcripts,
   reports) from the actual question you're asking. Each experiment plugs in
   its own definition of a "trial." Three experiments run on it today.

2. **A research direction.** The synthesis those experiments point toward:
   building a coding agent as a sequence of *tunable phases*. This is where the
   work is heading — see [The bet](#the-bet-plain-english).

---

## The bet (plain English)

A coding agent — the kind that fixes a GitHub issue — does a task in **stages**:

1. **Localization** — find *which* code needs changing
2. **Repair** — write the fix
3. **Test** — write and run tests
4. **Verify** — check it worked

**The idea:** treat each stage as a unit you can **stop at, snapshot, score,
and replay** — then, for each stage *separately*, **learn** the best setup
(which model, which prompt, how much context to feed it) instead of
hand-guessing one setup for the whole task. Localization might want a cheap
fast model; repair the smart expensive one. Today everyone uses one setup for
the whole task.

**Why it's a real idea:** normally you can't score a single stage — you only
find out if the *whole* task passed at the very end. Coding has a cheat: a
benchmark like SWE-bench already knows the right files, so you *can* score
"localization" on its own. That per-stage score is what makes per-stage tuning
possible.

**The catch:** that score only exists where there's an answer key. In a real
product there's no answer key for "did it find the right code" — only "do the
tests pass" at the end. So the plan is to **train the tuner offline on
benchmarks, then ship it frozen.** Whether that transfers to real tasks is the
central open question.

**The plan, one line:** get the staged agent working end-to-end → add per-stage
tuning → learn what to hand off between stages. Full version in
[`STRATEGY.md`](lib/agent-eval-core/STRATEGY.md).

---

## Start here (the docs)

All in [`lib/agent-eval-core/`](lib/agent-eval-core/), in reading order:

| Doc | What it's for |
|---|---|
| [`STRATEGY.md`](lib/agent-eval-core/STRATEGY.md) | **The plan of record.** Where we are, what we optimize for, the steps. Read first. |
| [`PLATFORM.md`](lib/agent-eval-core/PLATFORM.md) | The thesis in depth + the verified literature behind it (what's done, what's open). |
| [`TRACE.md`](lib/agent-eval-core/TRACE.md) | The session-trace interface spec (Step 0): is OTEL enough, the `PhaseNode` data model, the debug story. |
| [`SOTA.md`](lib/agent-eval-core/SOTA.md) | Context-engineering literature shelf, per topic. Reference, not narrative. |
| [`NEXT.md`](lib/agent-eval-core/NEXT.md) | Backlog of threads; defers to `STRATEGY.md`. |
| [`DIMENSIONS.md`](lib/agent-eval-core/DIMENSIONS.md) · [`HARNESS.md`](lib/agent-eval-core/HARNESS.md) · [`FAILURE_MODES.md`](lib/agent-eval-core/FAILURE_MODES.md) | What we measure, how the harness biases it, the failure taxonomy. |

---

## What's already built

### The bench: `agent-eval-core`

What you bring: a `trial = (model_client, condition, task) -> RunRecord`
function. What the library handles: model registry, sweep iteration,
parallelism, budget cap, pricing ($/Mtok with Jan 2026 prices), CSV/markdown
reports, per-trial transcript dumps. Domain-agnostic — it knows nothing about
formats / tools / retrievers.

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
[`lib/agent-eval-core/examples/`](lib/agent-eval-core/examples/).

### The experiments

| Experiment | Question | Headline finding |
|---|---|---|
| `code-editing` | How should LLMs express code edits — text replacement, diff, semantic ops, hybrid — and via tool_use, structured output, or agent loop? | **The protocol matters more than the format, and more than the model below Opus.** Structured JSON output lifts Sonnet 4.6 from 57% → 100% on 14 medium tasks. |
| `tool-selection` | How should LLMs *find* the right tool from a large catalog (full surfacing vs BM25 / embeddings / LLM router × phase architectures)? | **Two-phase (cheap classifier + smart generator) scales nearly flat** with catalog size; one-phase scales linearly worse. At 150 tools, 2phase-Haiku is 4× cheaper per success than 1phase-Haiku, 31× cheaper than 1phase-Sonnet. |
| `file-localization` | Can retrievers find the files an issue needs edited? (`recall@k`, `NDCG@k` on SWE-Bench gold patches.) | In progress — **and the on-ramp to the research direction:** localization is Step 1 of `STRATEGY.md`, the cleanest stage to score and tune first. |

Both `code-editing` and `tool-selection` independently observe the **Sonnet 4.6
one-call regression**
([anthropic-sdk-typescript#956](https://github.com/anthropics/anthropic-sdk-typescript/issues/956));
the generic conclusion is in
[`notes/tool-use-vs-structured-output.md`](notes/tool-use-vs-structured-output.md):
the canonical `tool_use` API is the wrong shape on two production scaling axes
(many tools, multi-step plans), and both workarounds bypass the API rather than
fight it.

---

## Quickstart

```bash
git clone git@github.com:AntoineToussaint/agent-bench.git
cd agent-bench
cp .env.example .env       # ANTHROPIC_API_KEY, OPENAI_API_KEY
uv sync                    # installs lib + all experiments

# run an experiment's CLI
uv run --package code-editing code-editing list-models
uv run --package code-editing code-editing list-formats

# run tests
uv run --package code-editing pytest experiments/code-editing/tests/ -q
uv run --package agent-eval-core pytest lib/agent-eval-core/tests/ -q
```

Each experiment is an independent uv package; all depend on `agent-eval-core` as
a workspace member.

## Layout

```
agent-bench/
  lib/
    agent-eval-core/         # the shared bench library (+ the strategy doc stack)
  experiments/
    code-editing/            # code-edit formats × protocols × models
    tool-selection/          # tool-catalog selection strategies × phases
    file-localization/       # SWE-bench file localization (= phase 1 on-ramp)
  notes/                     # cross-experiment findings, synthesis writeups
  results/                   # sweep outputs (gitignored bulk; some checked in)
```

## Why this exists

Most coding-agent benchmarks (SWE-Bench, Aider's polyglot, vendor evals)
hard-couple their measurement harness to one specific question, which makes it
hard to study orthogonal axes — protocol, format, selection strategy, model —
with the rest held constant. This repo separates the *infrastructure* from the
*question*: each experiment defines its own trial; the library handles the
rest. New experiments are ~1 day of domain code plus glue.

## Status

Active research. **Today:** the bench + the three experiments' findings + a
literature-verified thesis. **Next:** build the phased agent per
[`STRATEGY.md`](lib/agent-eval-core/STRATEGY.md). v0.x — the library API may
shift; pin to a SHA if you depend on it externally.
