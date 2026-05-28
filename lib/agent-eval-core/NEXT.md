# Next

Backlog of open threads. **The plan of record is `STRATEGY.md`** — it
sequences this work (localization-first) and maps several threads below
onto concrete steps. Read that first; this file is the menu it draws from.

Listed in roughly increasing ambition — pick whichever fits the next
sitting, not necessarily in order.

For *what we measure today* see `DIMENSIONS.md`. For *how the harness
biases observations* see `HARNESS.md`. For *failure taxonomy* see
`FAILURE_MODES.md`. For *published work per open thread + cross-cutting
gaps the bench can claim* see `SOTA.md`.

## Small, high-value (≤ half day each)

### Split `latency_seconds` into TTFT + generate
`#32` in the session task list. Today `latency_seconds` lumps queue +
prefill + decode into one number. Splitting them lets us answer "is
this model slow to *start* or slow to *generate*?" — currently
unknowable. Requires switching all three model clients
(Anthropic / OpenAI / Google) from `create` to `stream`, capturing a
monotonic timestamp at the first content delta. New fields
`TurnUsage.ttft_seconds` / `generate_seconds`. Pairs with
`batch_efficiency`: a chatty model with high TTFT pays the start-up
cost on every turn.

### Cold / observed / warm cost reporting
Today `cost_usd` is one number. It's neither the cold-start cost a
new deployment pays nor the steady-state cost a long-running
deployment pays — it's a single point on a curve. Report three:

| number | meaning |
|---|---|
| `cost_cold_start` | first-time call, no cache |
| `cost_observed` | what we actually saw (today's `cost_usd`) |
| `cost_warm_steady` | cacheable part has been in cache from the start |

Closes a real gap — "Don't Break the Cache" (2026) raised the
question; the bench should be where it gets answered. ~1-2 hours, all
in `agent_eval.pricing`.

### Persistent cost ledger
Append every trial to `~/.agent_eval/cost_ledger.jsonl` automatically
from the `Sweep` runner. Tiny CLI `agent-eval cost` for `--since`,
`--by-model`, `--by-sweep` queries. On by default; `--no-ledger` opts
out. ~30 minutes, mostly CLI plumbing.

## Medium (1-2 days each)

### Generalize `ContextPolicy` → `ContextEngineering`
Today's `ContextPolicy.prepare(messages, provider, turn_idx) → messages`
is too narrow — it only knows how to *prune*. Generalize to:

```python
class ContextEngineering(Protocol):
    name: str
    def prepare(self, state: TrialState) -> PreparedContext: ...
```

Deliberately under-specified. The runner trusts the result. Lets
people implement pruning, distillation, scoped routing, RAG-over-rules,
scratchpad systems, sub-agent briefs — all under one Protocol,
measured side-by-side.

Tier 1 policies (`KeepEverything`, `ToolResultElision`, `SlidingWindow`)
port onto it without behavior changes. They're three points in the
much larger space the new abstraction makes addressable.

### LLM-based distillation as a strategy
Once `ContextEngineering` exists, `DistillOldToolResults(distiller)` is
just one implementation. The distiller is configurable: model,
prompt template, task-context fields, max output tokens, cache key.

Bookkeeping: distillation cost + latency are tracked separately and
roll into `total_cost_usd`. Three new `RunRecord.extra` fields:
`distill_cost_usd` / `distill_latency_s` / `distill_calls`.

Ablation: same task, baseline vs LLM-distilled tail, measure cost
including distillation overhead and check pass-rate doesn't drop.
Tests whether [SWE-Pruner](https://arxiv.org/pdf/2601.16746)'s "compression
helps capability" finding reproduces in our setting.

## Larger (multi-session)

### Handoff-as-routing — the bun-vs-npm formalization
`#33` in the session task list. The example: `"use bun not npm"` in
CLAUDE.md costs tokens every turn and only ever matters when the
agent runs an install. The right design is *not* "always include it"
and *not* "compress it" — it's "scope it to the moment of need."

Concretely:
- `Atom` — content + tag-set scope (e.g. `tags=["bash", "installs"]`)
- `ContextStore` — registry of atoms, indexed by tag (YAML or
  directory of `.md` files with frontmatter)
- `Brief` — what a child sub-agent is born with: in-scope atoms +
  parent's findings + child's tool surface + task spec
- `HandoffPolicy` — `(parent_state, child_scope, child_task) → Brief`

First experiment: parent localizes the file (existing localize trial),
spawns a child with scope = `<language_of_the_file>`, child edits
with only the language-scoped atoms + the file pointer. Measure:
oracle pass; lint pass; whether atoms absent from scope caused
failures.

Two ablations that fall out:
- AlwaysOn vs ScopeRouted briefs (does the Go child do better
  with only Go atoms, or all language atoms?)
- Brief content variants: atoms-only / atoms+findings /
  atoms+findings+full-history

Maps to AgentAsk's 4 handoff failure modes (Data Gap, Signal
Corruption, Referential Drift, Capability Gap).

This is the real research thread. Production agents (Claude Code
subagents, Cursor's per-language modes) do something like this
informally; nobody publishes the ablation.

## Coverage / data-collection (no design, just runs)

### Populate `model_backends.yaml` empirically
Currently 3 of 9 recommendations have empirical backing (Haiku,
Sonnet from `protocol_matrix_v2/`; Gemini Flash from a 1-task smoke).
Run the 4-backend × N-task sweep on:
- `claude-opus-4-7`
- `gpt-5` (we have the client, no empirical runs)
- `gemini-2.5-pro`
- `gemini-2.5-flash-lite`

Each is ~12 trials × ~$0.10 = ~$5 of compute. The artifact: a
recommendation table backed by data instead of guesses.

### Harder tasks for the context-policy ablation
Tier 1 ablation showed 100% pass across all 3 policies — too easy a
task set to differentiate. Re-run on tasks where the baseline fails
sometimes (use `results/swebench_lite_difficulty.csv` to pick the
10-25% pass-rate band) and look for the failure-mode shifts the
classifier should be diagnosing.

---

## Stance

The interface for context engineering is **not solved** in the
published literature. The right move is to build the substrate where
multiple proposed interfaces are measurable side-by-side, not to
commit to one. Tier 1 is one valid implementation. The medium and
larger items above are alternatives, not extensions.

The novel claim the bench is moving toward: *cross-experiment failure-
mode classification + per-(model, backend) recommendations + cost
reported under cold/observed/warm assumptions + handoff-as-routing
ablations*. Each is unclaimed in published work alone. Together they
are the contribution.

---

For per-thread SOTA anchors and cross-cutting gaps the bench can
claim, see `SOTA.md`.
