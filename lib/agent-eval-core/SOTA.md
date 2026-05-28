# SOTA: Context Engineering for LLM Agents

State-of-the-art anchors for the open threads in `NEXT.md`. Each
section is keyed to one thread there, so the bench has concrete
published work to compare against — not just our own ideas.

Canonical entry point: [Survey of Context Engineering for LLMs
(arxiv 2507.13334)](https://arxiv.org/pdf/2507.13334) — 1400+ papers
catalogued; itself notes that evaluation methodology is fragmented
across the field.

---

## Anchors per open thread

### For "Generalize ContextPolicy → ContextEngineering"

This thread isn't anchored to a single paper — it's the substrate
that has to subsume all the families below. The breadth across the
other subsections (distillation, scope routing, atom stores, working
memory, dynamic tool surfaces) is exactly what justifies a
"deliberately under-specified" Protocol: no one abstraction in the
literature covers more than one of them.

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
- **[ACE-Router (Jan 2026)](https://arxiv.org/abs/2601.08276)** —
  history-aware routing across MCP tools + the broader agent web;
  trains a routing agent on multi-turn trajectories synthesized from
  a dependency graph over the candidate ecosystem.

**Underserved:** cache-invalidation cost when tools change is
acknowledged but barely measured. No benchmark reports tokens-billed-
as-cache-write vs cache-read when tool surfaces rotate. Tool Attention
is the only work that *designs around* it.

### Adjacent (not load-bearing)
- **["Just Ask" (Jan 2026)](https://arxiv.org/abs/2601.21233)** —
  system-prompt **extraction attack**; recovers prompts from 41
  frontier commercial code agents via UCB-based strategy selection.
  Not an evaluation framework. Listed only as evidence that production
  system prompts exist as recoverable monolithic artifacts — it does
  *not* support any claim about A/B testing or hand-authoring, so
  don't cite it for gap #1.

---

## Cross-cutting honest gaps

Five things nobody in published work has done. Each is a position the
bench can claim.

1. Production context-engineering (Claude Code, Cursor) is delivered
   as **system prompts with no released A/B data** — an observation
   from the absence of published evaluations, not a cited finding. We
   have not found a paper that ablates a production prompt; if one
   exists this gap shrinks.
2. Memory benchmarks score read-side QA; **write-side correctness,
   contradiction-handling, scratchpad ROI** are unmeasured.
3. **Cold-start / cache-warmth as a cost dimension** is named in
   blog posts but absent from peer-reviewed eval.
4. No benchmark systematically ablates **brief shape** for sub-agent
   handoff; the token-overhead multiplier (15× in Anthropic's
   multi-agent report, line above) is widely cited but never
   decomposed by what the brief actually contains.
5. No instruction-gating benchmark with conditional ground truth
   (rule should fire iff predicate X) exists. **The bun-vs-npm
   problem is unmeasured.**

These aren't independent — the substrate
(`ContextEngineering` Protocol + multi-cost reporting + failure-mode
classification) makes all of them measurable inside one research
instrument.

---

## Verification status

All arxiv IDs in this file were verified against arxiv (title + ID
confirmed) on 2026-05-28. MetaGPT, AutoGen, and Reflexion are
well-known classics, assumed safe and not re-fetched. Titles and
findings match the abstracts except for the two corrected below.

Corrected during verification:
- `2601.21233` "Just Ask" — paper is a system-prompt **extraction
  attack** on 41 commercial code agents, not an evaluation framework.
  Demoted to the "Adjacent (not load-bearing)" list; no longer
  supports gap #1.
- `2601.08276` was cited as "ToolACE-MCP"; actual title is
  **"ACE-Router"**. Subject matter (history-aware MCP routing) is
  correct; name updated.

Minor note: `2501.13956`'s formal title is "Zep: A Temporal Knowledge
Graph Architecture for Agent Memory" (Graphiti is its open-source
engine) — our "Zep / Graphiti" label is accurate enough to keep.
