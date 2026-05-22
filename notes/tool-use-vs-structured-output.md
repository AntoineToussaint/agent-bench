# The single-shot tool-use ceiling

## TL;DR

For batched code-edit tasks, **the provider tool-use API forces a "~1 call per response" ceiling on the model**, even when the model knows it needs to emit N operations. Reframing the same operations as a **structured text document** (JSON, SEARCH/REPLACE blocks, patch envelopes) lifts the ceiling — the model writes a complete document containing all N operations in one shot.

This is a property of the *protocol*, not the model.

> This is one of two findings about the canonical `tool_use` API that point the same direction. See **[Generic conclusion](#generic-conclusion-tool_use-is-the-wrong-shape-in-two-directions)** below for the combined story with the sister study on catalog-size scaling.

## The pattern

When asked to do a multi-step edit in single-shot tool-use mode, frontier models reliably:

1. Write an assistant-text plan listing all N edits.
2. Emit one `tool_use` block (for edit #1).
3. Stop — apparently waiting for a `tool_result` that will never come.

Example (Sonnet 4.6, task: add a refund feature touching `orders.py` AND `app.py`):

```
Assistant text:
  ## Plan
  1. Add refund_order to orders.py
  2. Add route_refund to app.py
  3. Update the import in app.py

Tool calls emitted: 1   (str_replace on orders.py only)
Result: oracle FAIL  (app.py untouched)
```

The model's plan is correct. The execution is truncated.

## Evidence

Same task (`c08_add_feature__medium`), same model, three protocols:

| Mode | Format | Tool calls emitted | Result |
|---|---|---:|---|
| `single` (tool_use) | search_replace | 1 | FAIL |
| `single` (tool_use) | semantic | 1–2 | FAIL |
| **`structured` (JSON text)** | semantic | **3** | **PASS** |

Same task, Haiku, semantic format:

| Mode | Tool calls | Result |
|---|---:|---|
| `single` (tool_use) | 1–4 | FAIL |
| `structured` (JSON text) | 3 | PASS |

Across the medium-task suite (n=14), `single`-mode `search_replace` averages **1.0 calls per response** regardless of how many edits the task needs.

## Quantified: 48-trial single vs structured comparison

We took the four medium tasks that consistently failed in single-shot tool_use mode across every format and every model (c04 signature_change, c05 api_migration, c08 add_feature, c09 remove_sweep) and ran them under both protocols, three formats (`search_replace`, `semantic`, `search_plus`), two models (Haiku 4.5, Sonnet 4.6). Same task contents, same model temperature (0), same applier code.

Headline:

| | `single` (tool_use) | `structured` (JSON text) |
|---|---:|---:|
| **Pass rate (n=24 cells)** | 8% | **79%** |
| **Calls per response** | ~1 (always 1 for sr/sr_plus) | 2–12 |

Per-task pass matrix (format×mode columns; ✓ pass / ✗ fail / N = number of operations emitted):

| Task | model | sr/single | sr/struct | sem/single | sem/struct | sp/single | sp/struct |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| c04 sig_change | Haiku | ✗ 1 | **✓ 2** | ✓ 3 | ✗ 2 | ✗ 1 | **✓ 2** |
| c04 sig_change | Sonnet | ✗ 1 | **✓ 2** | ✗ 1 | **✓ 2** | ✓ 1 | ✓ 2 |
| c05 api_migration | Haiku | ✗ 1 | **✓ 4** | ✗ 5 | **✓ 5** | ✗ 1 | **✓ 4** |
| c05 api_migration | Sonnet | ✗ 1 | **✓ 4** | ✗ 2 | **✓ 5** | ✗ 1 | **✓ 4** |
| c08 add_feature | Haiku | ✗ 1 | **✓ 3** | ✗ 3 | **✓ 3** | ✗ 1 | **✓ 3** |
| c08 add_feature | Sonnet | ✗ 1 | **✓ 3** | ✗ 1 | **✓ 5** | ✗ 1 | **✓ 3** |
| c09 remove_sweep | Haiku | ✗ 1 | ✗ 9 | ✗ 5 | ✗ 10 | ✗ 1 | ✗ 9 |
| c09 remove_sweep | Sonnet | ✗ 1 | **✓ 2** | ✗ 2 | ✗ 12 | ✗ 1 | **✓ 2** |

### What this tells us

**1. Protocol dominates format.** Whether the model uses text-edit (`sr`) or semantic ops (`semantic`) matters far less than whether it's writing tool_use blocks or a JSON document. The pass-rate gap (8% → 79%) is entirely a protocol effect.

**2. The format is no longer suppressed by the protocol.** In `single` mode, format choice barely mattered — the model emitted ~1 call regardless, packing as much change as the format allowed. In `structured` mode, each format gets to do what it was designed for:
  - `sr` issues 3–4 surgical replacements
  - `semantic` issues 5+ atomic refactor ops
  - `sr_plus` mixes both

**3. Call counts scale with task complexity in structured mode.** c04 needs ~2 edits → models emit 2. c05/c08 need ~3–5 → models emit 3–5. c09 needs ~6 → models emit 9–12 (trying hard but sometimes missing edges). In `single` mode all of these compressed to ~1 call.

**4. c09 isolates the residual difficulty.** Even with 10–12 structured calls and 5+ minutes of model compute, semantic on c09 still fails — the task ("remove `apply_shipping` and *every* reference including in 2 dependent functions, 2 constants, and the test imports") is genuinely hard for one-shot reasoning. Sonnet sr/sr_plus solve it cleanly with 2 calls by packing the function-and-callers into one big `str_replace` chunk. This is a real format insight that only shows up once protocol stops being the bottleneck.

**5. The breakthrough is reproducible across models.** Same uplift on Haiku 4.5 and Sonnet 4.6. Sonnet under `single` was actually *worse* at multi-call emission than Haiku (1 call vs 3–5 in semantic mode); under `structured` they converge to similar batch sizes. Suggests the tool-use single-call bias is *stronger in more capable models*, not weaker.

## Full 3-model × 2-mode matrix (n=14 medium tasks, search_plus format)

Same 14 medium-size tasks. Same `search_plus` format. Three models × two modes.

| | tool_use (single) | structured | Δ |
|---|---:|---:|---:|
| Haiku 4.5 | 50.0% | 85.7% | **+35.7pp** |
| Sonnet 4.6 | 57.1% | **100.0%** | **+42.9pp** |
| Opus 4.7 | 92.9% | **100.0%** | +7.1pp |

**Read this matrix as the resilience finding:**

| | range across models | meaning |
|---|---|---|
| tool_use spread | 50% → 93% (**43pp**) | strongly model-dependent — Sonnet/Haiku are starving in this protocol |
| structured spread | 86% → 100% (**14pp**) | weakly model-dependent — Haiku in this protocol matches Sonnet in tool_use |

**One protocol is much more resilient to model idiosyncrasies than the other.** Pick `structured` and your pass rate barely depends on which Claude you pick. Pick `tool_use` and you're paying a big "cheap-model tax" that compounds with the single-call bias.

Two observations to underline:

- **Sonnet 4.6 closes from 57% → 100% by switching protocol** (no model change). Pure protocol win.
- **Opus 4.7 only gains 7pp** because it already pushes back against the single-call reflex (1.6 avg tool calls per response in tool_use mode vs Sonnet's 1.0). Capability and protocol resilience trade off — the more capable model needs the protocol less.

Token efficiency follows the same pattern: structured uses ~17% fewer tokens per task than single across all three models (the model writes one focused JSON document instead of multiple round-trips with truncated context per turn).

The residual failures in structured mode are real-task-difficulty, not protocol artifact:

- Haiku-structured fails c09 (destructive multi-edit, same as in tool_use)
- Haiku-structured fails c01 (a JSON-parse / output-shape glitch — recoverable with a lenient parser)
- Sonnet-structured and Opus-structured pass all 14

## Opus 4.7 on the residual failure (c09)

c09 (`remove_sweep`: delete `apply_shipping` and every reference — touches 2 functions, 2 constants, the importer in tests, and a test file) was the only task semantic-structured couldn't solve on Sonnet or Haiku. Re-ran on Opus 4.7:

| format | mode | pass | calls | tokens |
|---|---|:---:|:---:|---:|
| search_replace | single | ✗ | 2 | 8.2k |
| search_replace | structured | ✓ | 3 | 8.2k |
| semantic | single | ✗ | 1 | 6.0k |
| **semantic** | **structured** | **✗** | **6** | 8.9k |
| search_plus | single | ✓ | 3 | 9.8k |
| search_plus | structured | ✓ | 3 | 8.4k |

Three observations:

**Opus pushes back against the single-call reflex more than Sonnet.** Opus single-mode `search_plus` emits 3 tool calls and passes. Sonnet always emits 1. Suggests the bias varies by model and Opus is partially trained out of it.

**`search_plus` single-shot is the first cell to pass c09 in non-structured mode** across any model. The hybrid (text-replace + `rename`/`move`/`change_value_of`) gave Opus enough text-edit breadth to pack the multi-edit chunks while still expressing the renames atomically.

**Semantic structured still fails on c09 even with Opus emitting 6 ops.** This isolates a real format-level finding: **destructive multi-edit tasks decompose poorly into atomic semantic ops.** Each of the 6 things needed (`remove function`, `remove constant` × 2, `replace function body` × 2, `update test imports`) is a distinct atomic op. The model has to enumerate every one without missing any. `search_replace` and `search_plus` solved the same task with 3 calls because one big `str_replace` packs multiple chunk-level changes in pricing.py simultaneously.

The asymmetry:

- **Additive multi-edit** tasks (`add this function, add this route, update this import`): both atomic semantic ops and text-chunk replacements work in structured mode, because each edit has a clean local target.
- **Destructive multi-edit** tasks (`remove this and every reference`): text-chunk replacement is materially better, because chunking lets the model rewrite multiple co-located edits at once without enumerating each.

Atomic ops are like Lisp's "do one thing" primitives. Chunk replacement is like sed across a region. For pure refactors over named entities (rename, move) atomic wins. For tear-out edits, chunked text wins.

## Why this happens

Tool-use is trained on a **multi-turn action-feedback loop**:

```
model → tool_use → harness → tool_result → model → tool_use → ...
```

In that loop, "emit one call, await result" is the rational pattern. The training reinforces it. Even when we tell the model "you have only one response, emit everything", the trained reflex wins.

Structured text output has no such reflex. The model is *writing a document*, and a complete document includes everything. JSON arrays with three entries are as natural as JSON arrays with one entry.

## When tool_use is right

- Multi-turn agents where the result of action N genuinely informs action N+1 (search → read → edit → run tests)
- Single discrete actions (look up a value, send a message, query an API)
- Schema-validated inputs where the provider's JSON-schema enforcement matters
- Prompt caching wins on Anthropic (tool definitions cache well)

## When tool_use is wrong

- **Batched code edits where the plan is fixed up front** — pre-known multi-file refactors, codemods, "fix this set of issues"
- Any case where the per-call "result" is just OK/error and provides no information that affects the next call
- Single-shot evaluations of model-edit quality (you're measuring the protocol's ceiling, not the model's capability)

## Recommended pattern: structured text output

For batched edits, frame the operations as a **document the model writes**:

```json
{
  "plan": "<brief description per planned edit>",
  "changes": [
    {"op": "rename", "paths": [...], "old_name": "...", "new_name": "..."},
    {"op": "str_replace", "path": "...", "old_str": "...", "new_str": "..."},
    {"op": "add", "path": "...", "new_source": "..."}
  ]
}
```

Then parse and apply server-side. The model writes one coherent JSON object with N changes — no "wait for result" reflex.

This is also Aider's pattern (SEARCH/REPLACE blocks in text), Cursor's pattern (code blocks with `// ... existing code ...` markers + a separate apply model), and OpenAI Codex CLI's pattern (`*** Begin Patch` envelopes). All three independently converged on "edit-as-document" instead of "edit-as-tool-call."

## Caveats

- This is empirical, from our own runs. Anthropic's tool-use training may change. We've seen it consistently across Haiku 4.5 and Sonnet 4.6.
- Structured output loses the provider's automatic schema validation. You'll get malformed JSON occasionally and need a parser that's tolerant (multiple code blocks, partial recovery).
- Provider prompt-cache wins still favor tool_use in many real systems. The tradeoff: cache hit rate vs single-shot batch quality.
- For *single-action* edits, tool_use is fine and more ergonomic.

## Test for your own use case

If your task involves emitting **3+ coordinated operations in one shot**, run both protocols head-to-head and compare:

- Number of operations the model actually emits per response
- Pass rate on completion of the full task
- Token cost per successful task

We measured a clear protocol gap on our 14-task medium suite. Run it on yours.

## Generic conclusion: tool_use is the wrong shape in two directions

The single-call ceiling above is one of two independent failure modes of the canonical `tool_use` API at production scale. A parallel study ([tool-selection](https://github.com/AntoineToussaint/tool-selection), May 2026) measured the other one: **catalog-size bloat**.

| Axis | Failure mode | Mitigation | Measured by |
|---|---|---|---|
| **Scaling out** — catalog size | Every tool's schema lives in context. Cache invalidates on any tool-set change. Past ~40 tools, selection accuracy degrades and per-request cost grows linearly. | **Two-phase**: a cheap model selects relevant tools first; a smart model generates arguments for one tool at a time. | [`tool-selection`](https://github.com/AntoineToussaint/tool-selection) |
| **Scaling up** — multi-step batches | Model emits ~1 `tool_use` block per response regardless of how many operations the task needs. Plan-first prompting does not rescue this. | **Structured output**: emit the full operation set as a JSON document in plain text. Parse + apply. Bypass `tool_use` for the batched stretch. | this repo |

Both studies independently observed the **Sonnet 4.6 one-call regression** ([anthropic-sdk-typescript#956](https://github.com/anthropics/anthropic-sdk-typescript/issues/956)) and verified that **plan-first prompting cannot fix it** — the behavior is structural to the tool_use protocol, not in the system prompt.

### Quantified, in one matrix

Combining both studies (numbers approximate, see source repos for exact methodology):

| | `tool_use` (canonical) | structured / two-phase | factor |
|---|---:|---:|---:|
| Pass@1 on multi-step edits (Sonnet 4.6) | 57% | **100%** | **+43pp** |
| Cost-per-success at 150 tools (Haiku 4.5) | $0.055 | **$0.014** | **~4× cheaper** |
| Model-resilience spread on 14 tasks | 43pp (50→93%) | **14pp (86→100%)** | **~3× less model-dependent** |

### The compound shape

These aren't unrelated bugs. They're the same root cause showing up at two different boundaries:

```
tool_use API design assumption:
  "Each model response is one discrete action that produces a result
   the model needs before deciding the next action."

Production reality (axis 1 — many tools):
  The model has 80+ candidate tools available at any moment. Loading them
  all costs tokens regardless of which one fires. Tool definitions live
  at the top of context — cache-hostile to any dynamic selection.

Production reality (axis 2 — known multi-step plans):
  The model already knows its full N-step plan (it just wrote it in
  assistant text). There's no information that "wait for tool result"
  would add. But the trained reflex returns ~1 call per response.

In both cases the canonical API forces the model to roundtrip when a
single concentrated output would do.
```

### What production systems actually do

Mature systems have already evolved past the canonical pattern, independently of each other:

- **Aider, Cursor, OpenAI Codex CLI**: edits as text documents (SEARCH/REPLACE blocks, code-fence + apply model, `*** Begin Patch` envelopes). Bypasses `tool_use` for the batched output.
- **Anthropic's Tool Search Tool, AgentFlux, HyFunc, RAG-MCP**: two-phase tool selection. Bypasses `tool_use` for the wide catalog.
- **Both together** in agent frameworks like Sweep, Cline, OpenRewrite: selection happens server-side; edits happen as text emissions; only narrow status/control calls use `tool_use`.

The empirical pattern is clear: **`tool_use` is correct for the shape it was designed for — a single, well-known action whose result the model needs before continuing.** For batched plans, frame edits as a structured text document. For wide catalogs, frame selection as a separate cheaper pass. The "obvious" path of "expose everything via `tool_use` and let the model figure it out" is the wrong design at production scale on both axes.

### Practical decision tree

If you are building an LLM agent system today:

```
Catalog size > ~30 tools?
  └── YES: use two-phase selection (cheap model + smart model)
  └── NO: tool_use catalog is fine

Single response needs to emit > 2 coordinated operations?
  └── YES: use structured text output (JSON change-set or SEARCH/REPLACE blocks)
  └── NO: tool_use is fine

If either YES — do NOT expect prompt engineering to overcome the structural bias.
The provider's tool_use training is doing what it was trained for; you need to
side-step the protocol, not argue with it.
```

### Open questions

- Does GPT-5 / Gemini 3 / open-weight models exhibit the same single-call reflex? We tested only Anthropic. The Sonnet 4.6 regression is the strongest single-call bias we observed; Opus 4.7 partly trains it out (1.6 avg calls per response).
- Does the structured-output workaround degrade as the change-set grows past ~20 operations? Untested.
- Can a custom fine-tune put both fixes inside the canonical `tool_use` API? Likely yes — this is fundamentally a training-distribution problem, not a fundamental API limit. But until that fine-tune ships, the workarounds are the right pattern.
