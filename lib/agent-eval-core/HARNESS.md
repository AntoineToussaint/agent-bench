# The harness itself

What sits between the model and the task. This document treats the
harness as a *research object* — its policies, defaults, and hidden
hyperparameters all bias what we observe. Naming them lets us measure
them.

For *what* we measure end-to-end, see `DIMENSIONS.md`.
For *how* trials fail, see `FAILURE_MODES.md`.

## Why this document exists

When we say "Haiku passes 80% on file-localization," we really mean
"Haiku-with-our-context-policy-our-tool-truncation-our-retry-policy
passes 80%." Each of those policies is a hyperparameter of the harness,
not the model. If we want our recommendations to be portable — "use
Native backend with Haiku on localization tasks" — we have to know
which observations are about *Haiku* and which are about *our harness*.

## The big one: context engineering

**Today's policy: keep everything verbatim.** Every turn re-sends the
full conversation history. No summarization, no pruning, no tool-result
elision after the fact.

```
turn 1: system + user + (assistant_1 + tool_results_1)
turn 2: system + user + (assistant_1 + tool_results_1)
                       + (assistant_2 + tool_results_2)
turn 3: …everything from turns 1+2 + (assistant_3 + tool_results_3)
…
```

This is the *simplest* policy and it's what we ship. It works for ~10-turn
trials. It is **not** what production agents do — Claude Code, Aider,
Cursor, and Cline all have sophisticated context management
(summarization, expiry, tool-result pruning, sub-agent delegation).

### Why this is a hidden variable

A model's behavior changes when its context bloats. Empirical anecdotes:

- **Lost-in-the-middle** (Liu et al., 2023): performance drops when key
  context is in the middle of a long prompt.
- **MAST FM-2.3** (context-amnesia): agents forget facts emitted
  earlier when the context grows.
- **Anthropic's own caching docs**: cache-read tokens are 10× cheaper,
  but only when the cached prefix matches. Our naive "keep everything"
  policy *maximizes* cache hits — but in production an agent might
  prune *exactly* the prefix that was cached, making real-world cost
  estimates from our numbers misleading.

### What we now measure

As of this commit, every turn-loop trial reports:

| field on `RunRecord.extra` | meaning |
|---|---|
| `peak_input_tokens` | max input_tokens any single turn used |
| `input_tokens_at_done` | context size on the final turn |
| `context_growth_per_turn` | mean input_tokens delta turn-over-turn |

These are *observation* metrics, not knobs — we still keep everything.
The goal is: if Haiku at turn 8 starts misbehaving when input_tokens
crosses 5000, we'd see that in the data.

### What we don't yet do (proposals)

Three policies worth ablating later:

1. **Tool-result truncation after N turns** — keep the most recent tool
   result verbatim, replace older ones with a summary placeholder. Production
   default in most agents. Probably saves 30-70% of tokens on long trials.
2. **Sliding-window context** — drop turns older than N. Crude but cheap.
3. **Summarization** — replace pruned turns with an LLM-generated summary.
   Adds cost but preserves more info.

Each could become a `ContextPolicy` abstraction analogous to `ToolBackend`,
selectable per trial. Same shape: bundle a strategy onto `ModelHandle`,
let the trial loop call `policy.prepare(messages)` before each `step()`.

## Other harness dimensions worth naming

These don't have instrumentation yet but are worth being explicit about.

### Tool-result truncation
Hardcoded character caps (e.g. 8000 for `view_file` / `grep` in
file-localization). When a model fails to find something past the cap,
it looks like a model failure but might be a harness one.

### Concurrency within a turn
Per-turn tool calls are dispatched **serially** in a `for` loop. A model
that batches 5 view_files into one turn pays 5× the latency of a model
that batches 1. This artificially advantages chatty models on
wall-clock latency and disadvantages the "smart batching" they're
trying to do. Fixable with `asyncio.gather`.

### Rate-limit & retry
None. A 429 from any provider kills the trial with `model_error`. Real
harnesses implement exponential backoff. Important for any sweep
beyond ~50 trials.

### Token budgets at the trial level
We cap `max_tokens` per response and `max_turns` for the trial. We do
not cap total token spend per trial. Pathological models can blow the
expected cost by 10x without our noticing until the sweep finishes.

### Determinism
We set `temperature=0` where the API allows it. We do NOT seed sampling.
Two runs of the same trial can differ. Observed: Haiku one-shot
oscillated 60% → 20% → 40% across runs of the same code in earlier
sessions — that's the determinism floor, and our 3-task smokes can't
distinguish "model noise" from "real signal" beneath it.

### Tool description quality
Tool schemas live in each experiment (`tools.py`). They're hand-written.
We've seen wrong descriptions cause confusable-sibling failures. The
harness doesn't measure description quality or A/B test alternatives.

### Sandbox isolation
Code-editing runs in tmp dirs (good). But subprocess time/CPU/memory
limits, network access, file-system reach are *not* sandboxed beyond
"the tools we expose don't include bash." Adding a shell-tool experiment
would force us to confront this.

## Reading guide

When citing a finding from this repo, the responsible default is to
note which harness policies were in force. The most-cited one for now:

> "Measured under the [agent-bench v0.1] harness — full-context replay,
> 8KB tool-result truncation, serial within-turn dispatch, temperature=0
> where supported, no retry on rate-limit."

The future state — where each policy is selectable — lets findings
say "under context policy = `summarize_after_5_turns`," etc., which
both makes results portable and turns the harness itself into something
ablatable.
