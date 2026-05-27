# Next

Open threads from the most recent session. Listed in roughly increasing
ambition — pick whichever fits the next sitting, not necessarily in order.

For *what we measure today* see `DIMENSIONS.md`. For *how the harness
biases observations* see `HARNESS.md`. For *failure taxonomy* see
`FAILURE_MODES.md`.

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

## SOTA anchors per open thread

Concrete published work to ground each open thread above. The
canonical entry point is the [Survey of Context Engineering for LLMs
(arxiv 2507.13334)](https://arxiv.org/pdf/2507.13334) — 1400+ papers
catalogued; itself notes the evaluation methodology is fragmented.

### For "Generalize ContextPolicy → ContextEngineering"

The Protocol shape we're aiming at has to cover at least these
distinct families (each cited below). That breadth is what
justifies "deliberately under-specified."

### For LLM-based distillation
- **[SWE-Pruner (Jan 2026)](https://arxiv.org/pdf/2601.16746)** — 0.6B
  goal-conditioned skimmer; 23-54% token reduction *with* success-rate
  improvement on SWE-Bench. The reference result we're trying to
  reproduce / extend.
- **[Agentic Plan Caching (NeurIPS 2025)](https://arxiv.org/abs/2506.14852)**
  — different layer (plan templates, not message tail), but the same
  spirit: precompute, reuse. −50% cost, −27% latency.

### For Handoff-as-routing (the bun-vs-npm thread)
- **[Anthropic multi-agent research system (Jun 2025)](https://simonwillison.net/2025/Jun/14/multi-agent-research-system/)**
  — concrete brief structure: objective + boundaries + output format
  + tool guidance + cardinality rules. +90% over single-agent Opus 4
  at 15× tokens. **No public ablation of brief shape.**
- **[MetaGPT](https://arxiv.org/pdf/2308.00352)** — SOP-encoded role
  prompts; structured deliverables passed verbatim role-to-role.
- **[AutoGen](https://ar5iv.labs.arxiv.org/html/2308.08155)** —
  free-form chat between controller and workers (the opposite end of
  the design space from MetaGPT).
- **[AgentAsk (Oct 2025)](https://arxiv.org/html/2510.07593)** — 4
  handoff failure modes (Data Gap, Signal Corruption, Referential
  Drift, Capability Gap). **No benchmark scores brief shape directly.**

### For atom-level / structured-fact stores
- **[Zep / Graphiti (Jan 2025)](https://arxiv.org/abs/2501.13956)** —
  bitemporal knowledge graph; +18.5% acc, −90% latency on
  LongMemEval. State-of-the-art memory system to compare against.
- **[A-MEM (Feb 2025)](https://arxiv.org/abs/2502.12110)** —
  Zettelkasten-style self-organizing notes. Tested on LoCoMo across
  six base models.
- **[Letta memory blocks (docs)](https://docs.letta.com/guides/agents/memory-blocks/)**
  — agent-editable named blocks; production framework, no peer-reviewed
  eval. Closest existing example of "atoms with explicit slots."

### For scope routing (the CLAUDE.md problem)
- **[MemTool (Jul 2025)](https://arxiv.org/pdf/2507.21428)** — autonomous
  / workflow / hybrid modes for swapping tool schemas in/out of
  short-term memory. Reports tool-removal ratio + completion accuracy
  on ScaleMCP-334K across 100-turn sessions.
- **[Tool Attention Is All You Need (2026)](https://arxiv.org/html/2604.21816v1)**
  — lazy schema loading + dynamic tool gating; explicitly designs the
  prompt layout (stable prefix vs volatile suffix) to minimize cache
  invalidation when tools rotate.
- **["Just Ask" (Jan 2026)](https://arxiv.org/pdf/2601.21233)** —
  documents that Claude Code / Cursor / Copilot system prompts are
  hand-authored. **Explicit confirmation that scope routing is
  hand-tuned in production with no published A/B framework.**

### For cache-aware harness design (cold/observed/warm)
- **["Don't Break the Cache" (Jan 2026)](https://arxiv.org/html/2601.06007v2)**
  — four caching policies on DeepResearch; measures cost + TTFT but
  not task success. Treats cache warmth as binary, not as a deployment
  dimension. The gap we're closing.
- **[Tool Attention (2026)](https://arxiv.org/html/2604.21816v1)** —
  the only work designing prompt *layout* for cache friendliness.
- **OpenAI Agents SDK MCP** ([docs](https://openai.github.io/openai-agents-python/mcp/))
  — `cache_tools_list` + `invalidate_tools_cache()`. Production knob,
  no published evaluation.

### For working memory / scratchpad
- **[Reflexion (2023)](https://arxiv.org/pdf/2303.11366)** — canonical
  verbal-self-reflection-as-memory. Scratchpad-as-policy baseline.
- **[Hindsight is 20/20 (Dec 2025)](https://arxiv.org/pdf/2512.12818)**
  — retain / recall / reflect tri-loop.
- **[MEMTRACK (Oct 2025)](https://arxiv.org/pdf/2510.01353)** —
  long-term **state-tracking** eval (vs simple recall).
- LoCoMo + LongMemEval + BEAM are the de-facto memory benchmarks
  ([mem0 state-of-2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)).
  **All test read-side recall; none test write-side correctness or
  scratchpad ROI directly.**

### For dynamic tool surfaces
- **[ScaleMCP (May 2025)](https://arxiv.org/pdf/2505.06416)** —
  hash-based auto-sync of agent tool index with MCP source-of-truth.
- **[MCP-Zero (Jun 2025)](https://arxiv.org/pdf/2506.01056)** — agent
  actively discovers tools mid-task.
- **[MCPAgentBench (Dec 2025)](https://arxiv.org/html/2512.24565v1)**
  — real-world MCP task benchmark.
- **[ToolACE-MCP (Jan 2026)](https://arxiv.org/html/2601.08276v1)** —
  history-aware tool routing.

**Underserved:** cache-invalidation cost when tools change is
acknowledged but barely measured. No benchmark reports tokens-billed-
as-cache-write vs cache-read when tool surfaces rotate. Tool Attention
is the only work that *designs around* it.

---

## Cross-cutting honest gaps (from the survey)

1. Most production context-engineering wins (Claude Code, Cursor)
   are **hand-tuned system prompts with no released A/B data.**
2. Memory benchmarks score read-side QA; **write-side correctness,
   contradiction-handling, scratchpad ROI** are unmeasured.
3. **Cold-start / cache-warmth as a cost dimension** is named in
   blog posts but absent from peer-reviewed eval.
4. No benchmark systematically ablates **brief shape** for sub-agent
   handoff; the 3-10× token-overhead figure is widely cited but not
   decomposed.
5. No instruction-gating benchmark with conditional ground truth
   (rule should fire iff predicate X) exists. **The bun-vs-npm
   problem is unmeasured.**

Each gap is a position the bench can claim. They aren't independent —
the substrate (`ContextEngineering` Protocol + multi-cost reporting +
failure-mode classification) makes all of them measurable inside one
research instrument.
