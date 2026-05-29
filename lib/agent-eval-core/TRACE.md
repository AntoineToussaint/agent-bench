# Trace / session interface

The spec Step 0 of `STRATEGY.md` builds toward: the canonical object the
platform records, scores, debugs, and forks against. Grounded in two
verified SOTA digs (2026-05-29); sources inline.

---

## The question

We already emit OpenTelemetry spans (`sweep > trial > turn > {llm.request,
tool_call}`) following the OTEL GenAI semantic conventions. Is that enough as
the canonical trace, or do we need something richer?

## Verdict: OTEL is necessary but not sufficient

Keep emitting OTEL spans as the **observability / wire format** — it's the
converging industry standard and buys free integration with every backend. But
make the canonical object a **richer "session trajectory" type that *emits*
OTEL**, because three of our four needs are *fundamentally* outside OTEL's data
model — not merely unimplemented:

| Need | OTEL span attribute? | Why / why not |
|---|---|---|
| Config provenance ({model, prompt, context-strategy} per phase) | **Yes** | maps to custom + `gen_ai.request.*` attributes cleanly |
| Per-phase verifiable reward on a segment | **No** | a span is immutable + point-in-time; rewards are computed *after* it closes. OTEL has no score primitive. |
| Restorable conversation + environment state at a boundary | **No** | spans are event records, not state snapshots; a blob in an attribute has no schema, addressing, or restore semantics |
| Fork / replay from a boundary | **No** | trace context (`trace_id`/`span_id`/parent) models *causality of one execution*, not *branching into alternatives* |

Two facts that reinforce this:
- OTEL GenAI conventions are still **"Development" (experimental)** as of 2026,
  not frozen; message content is **opt-in** and SHOULD NOT be captured by
  default.
  ([spec](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/),
  [agent spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/))
- There is **no cross-vendor "agent trajectory" interchange standard**. The
  trajectory-with-checkpoints-and-rewards object we want is exactly the gap the
  observability standards deliberately leave open.

---

## The data model: a node in a tree, two state planes

Model a phase boundary as a node in a tree. Fork = N children sharing one
`parent_id`. The node joins two deliberately-separate state planes (their cost
and lifetime differ by orders of magnitude — keep them as distinct refs).

```
PhaseNode {
  id, parent_id,            // the DAG edge — fork = N children share parent_id
  phase: localize|repair|test|verify,
  config: {model, prompt_id, context_strategy},   // the bandit arm (Step 2)
  conv_ref:  pointer,       // plane 1: conversation snapshot (cheap, JSON)
  env_ref:   (P_j, F_k) | null,   // plane 2: process + filesystem (expensive)
  reward:    {value, kind: oracle|prod, detail} | null,   // attached at node
  span_id, trace_id,        // link into the OTEL observability trace
  metadata:  {step, created_at, ...}
}

SessionTrace = the tree of PhaseNodes for one task, + helpers:
  fork(at_phase, new_config) -> restores conv_ref (+ env_ref) and re-runs.
```

### Prior art to borrow (don't invent)
- **Plane 1 — conversation:** LangGraph's `StateSnapshot` + `parent_config` is a
  shipped checkpoint **DAG** keyed by `thread_id`/`checkpoint_id`; fork via
  `update_state(...)` then `invoke(None, fork_config)` (re-runs successors —
  exactly our "fork into N variants").
  ([time-travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel),
  [persistence](https://docs.langchain.com/oss/python/langgraph/persistence))
  The minimal zero-dependency equivalent: an append-only JSONL log, fork = copy
  up to line N — which is literally how **Claude Code** stores sessions under
  `~/.claude/projects/` to enable rewind/resume/fork.
- **Plane 2 — repo/container:** **Crab**'s recovery tuple `Cᵢ = (Pⱼ, Fₖ)`
  (process + filesystem refs, paired, independently versioned) — arXiv
  **2604.28138** (verified). Semantics-gated: 70–87% of turns need no
  checkpoint; supports RL rollout branching with prefix reuse (40–64% token
  reduction). **DeltaBox** (arXiv **2605.22781**, verified) is the ms-class C/R
  companion if deep tree search ever needs it.
- **Reward attachment:** **Langfuse `Score`** (Numeric/Categorical/Boolean/Text,
  attaches to a trace **or observation/segment**) — the cleanest
  segment-scoped reward model
  ([scores](https://langfuse.com/docs/evaluation/scores/data-model)).
  **Braintrust** spans make `input`/`output`/**`expected`**/**`scores`**
  first-class — borrow the ground-truth-vs-actual shape
  ([advanced tracing](https://www.braintrust.dev/docs/instrument/advanced-tracing)).
- **External-blob-by-reference:** **MLflow Trace** keeps the span lightweight
  and stores large attachments externally, referenced by URI — the pattern for
  `conv_ref`/`env_ref` (don't inline snapshots into the trace)
  ([trace model](https://mlflow.org/docs/latest/genai/concepts/trace/)).

---

## How this maps to the build (cheap first)

The two planes let us build and validate the whole interface on the cheapest
phase before touching snapshot infra:

- **Localization is read-only** — it reads files to find them, never mutates the
  repo. So `env_ref = null`; the checkpoint is **just `conv_ref`**. We can prove
  the entire `PhaseNode` + fork + per-phase-reward loop on localization with
  nothing but a serialized conversation. (This is *why* localization is Step 1.)
- **Repair onward mutates the repo** — set `env_ref` to a **git commit/branch**
  (cheapest correct snapshot; working-tree only, no process state).
- **Phases with live processes** (e.g. a running test server in `test`) — only
  then reach for full snapshots: ZFS+CRIU à la Crab (DIY) or a managed
  **Modal Memory/Filesystem Snapshot** / **Morph branch** for fan-out
  ([Modal snapshots](https://modal.com/docs/guide/sandbox-snapshots)).

**Do NOT build on a durable-execution engine first** (Temporal/DBOS/Inngest).
They optimize *resume with memoized step output*, which fights our need to
**re-sample** a forked phase under a new config (a replayed step returns the
recorded output, not a fresh generation). They also don't checkpoint the
environment plane at all. Keep a plain `PhaseNode` tree as the source of truth;
adopt a durable engine only if fault-tolerant long runs at scale ever demand it.

---

## Bonus: this is also the best debugging substrate

The same object serves three masters, which is the real argument for making it
canonical rather than bolting reward onto spans:

1. **Observability** — it emits OTEL spans; every node carries `span_id`/
   `trace_id`, so a row in Honeycomb/Langfuse still points at the checkpoint
   that produced it.
2. **Debugging** — how people debug agents today is (a) step through the
   trace/run tree (LangSmith, Langfuse, Phoenix, Braintrust, Weave), (b) read
   the raw transcript, (c) **time-travel: rewind to the step before the failure
   and re-run just that part** (LangGraph), (d) score-driven triage of failing
   traces. Our phase structure upgrades all of these: per-phase reward answers
   **"which phase failed?"** instantly instead of scrolling 30 turns; `fork()`
   is **"re-run just the repair phase from the post-localization checkpoint"**;
   and the existing `failure_modes.py` classifier becomes *per-phase*
   ("repair failed via referential drift in the handoff," not "trial failed").
3. **RL / bandit** — checkpoint + per-phase reward + config provenance is
   exactly the training signal (Steps 2–3 of `STRATEGY.md`).

---

## Read first
1. **Crab** — arXiv [2604.28138](https://arxiv.org/abs/2604.28138). Closest
   existing system: phase/turn-boundary checkpoints, the `(P,F)` fork tuple, RL
   rollout branching, and the cost data justifying *semantics-gated* (not
   every-boundary) checkpointing.
2. **LangGraph time-travel + persistence**
   ([time-travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel),
   [persistence](https://docs.langchain.com/oss/python/langgraph/persistence)) —
   the cleanest shipped conversation-state checkpoint DAG + fork API (plane 1).
3. **Modal sandbox snapshots**
   ([docs](https://modal.com/docs/guide/sandbox-snapshots)) — the most concrete
   *managed* snapshot+restore-into-N-sandboxes API (plane 2), to prototype env
   fork without building ZFS/CRIU. Pair with **DeltaBox** (arXiv
   [2605.22781](https://arxiv.org/abs/2605.22781)) for ms-class C/R later.

## Caveats
- OTEL GenAI is experimental; pin the convention version you depend on.
- OpenInference (Arize) is a *separate* span convention, not an OTEL subset; no
  published convergence plan (issue Arize-ai/openinference#2130 unanswered).
- `verifiers`' "branching rollouts" is trajectory-level, not a checkpoint tree —
  weakly supported; don't assume it gives you node-level fork.
- Morph's sub-250ms branch latency is vendor-sourced, uncorroborated.
