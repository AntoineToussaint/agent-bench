# Strategy

The plan of record. `PLATFORM.md` argues the thesis and cites the
verified landscape; `SOTA.md` anchors the context-engineering
literature; `NEXT.md` is the backlog. This file says **where we are**
and **what to do in what order, and why**.

---

## Where we are

**The instrument (built, 7 commits, 121 tests):**
- Unified `ModelHandle + ToolBackend + OTEL` substrate across Anthropic /
  OpenAI / Google clients; pricing + backend YAML wired.
- Failure-mode classifier; `DIMENSIONS.md` / `HARNESS.md` / `FAILURE_MODES.md`
  position the bench against SOTA.
- Tier-1 context engineering: `ContextPolicy` abstraction + 3 policies. First
  ablation: `ToolResultElision` cut cost 45% at unchanged accuracy on 3
  astropy tasks — but all 3 policies passed 100%, so the task set is too easy
  to differentiate (a known limitation).

**The thesis (crystallized this session, fully literature-verified):**
A coding agent runs through fixed phases — localization → repair →
test-writing → verification. Make each phase a checkpointable, resettable,
**heterogeneously-rewardable** sub-environment whose **action space includes
the config bundle {model × prompt × context-strategy}**, learned per-phase
against a *verifiable* phase reward.

**Why this is the right bet (from the two verified digs):**
The config-optimization literature's central pain is per-stage credit
assignment — DSPy collapses it to a global metric, Optimas *learns a surrogate*
local reward because a real one is unavailable. A phase-segmented environment
**supplies the ground-truth per-phase reward for free.** The two ideas solve
each other's hard problem. Nobody occupies the intersection; the nearest
neighbors each miss on one defensible axis (Optimas: surrogate reward, not
phase-structured; LLMSelector: model-only, estimated reward; DSPy: prompt-only,
global metric). SGAgent (`2602.23647`) shows shipped agents already phase the
work but run one config across all phases — the gap is live, not hypothetical.

---

## The strategic situation

- **The moat is narrow and specific:** *heterogeneous verifiable reward per
  phase* + *config-bundle-as-action*. NOT the phase decomposition (Agentless
  owns that) and NOT checkpoint infra (Crab owns that). Lead every framing with
  those two.
- **The window is closing:** the most relevant papers are Jan–Apr 2026. The
  modular pieces are all on the table; a "phase-aware SWE-Gym" is gluable within
  a quarter by someone else. Implication: **get one defensible, verifiable
  result out fast on the narrowest slice, before building the general system.**
- **One genuine research risk:** phase boundaries are fuzzy — real agents
  interleave localization and repair. "Where does a phase end?" must be answered
  operationally, not assumed.

---

## Strategy: narrow-and-deep, then widen

Derisk by proving the thesis on the single cleanest phase before generalizing.
Each step produces a standalone result and de-risks the next.

### Step 0 — The reset/reward primitive (substrate)
Add to the existing harness:
- `reset_to_phase_boundary(state)` — snapshot/restore repo + conversation +
  tool state at a phase edge.
- a per-phase **verifiable reward** hook.

**Build cheap first.** Start with git-state + serialized-conversation snapshots,
not container C/R. Adopt Crab-style (`2604.28138`) eBPF checkpointing only if
cheap snapshots prove insufficient. Reuse existing OTEL + `ToolBackend`. This is
the one piece of new infra everything else needs.

### Step 1 — Localization as a standalone verifiable sub-environment
Localization has the **cleanest verifiable reward**: gold files/functions are
known from the SWE-bench patch → Hit@k / MRR. Reproduce Agentless
(`2407.01489`) localization as the baseline. Deliverable: *run agent, stop after
localization, score it.* This is the minimum viable demonstration of the thesis
and validates Step 0.

### Step 2 — Config-bundle-as-action on the localization phase (first real result)
Vary {model × prompt × context-strategy} for localization; measure the phase
reward. Frame as a **contextual bandit over config bundles** with a verifiable
reward. This is the first defensible, ownable result and directly exhibits the
deltas vs LLMSelector (verifiable not estimated reward) and DSPy (bundle not
prompt-only). **Start as a bandit, not full RL** (see Decision A).

### Step 3 — Handoff brief as a learnable context-strategy action (sharpest claim)
Fork from the post-localization checkpoint; learn *what compressed context to
pass into repair*; reward by the repair phase's verifier. This is the single
most ownable sub-claim — "context-strategy as action" meets "per-phase
verifiable reward" — and it closes the handoff-as-routing thread in `NEXT.md`.
The bun-vs-npm example is the verifiable testbed for the gating variant.

### Step 4 — Compose per-phase + end-to-end
Full localize→repair→test→verify pipeline with per-phase rewards AND an
end-to-end reward. Measure the headline scientific question: **do phase-local
verifiable rewards reduce the credit-assignment variance that iStar/HiPER
complain about?** This is the result that justifies the whole frame.

---

## Decisions to make early (don't drift on these)

- **A. Bandit vs full RL.** LLMSelector (`2502.14815`) assumes end-to-end
  performance is monotonic in per-module quality, so greedy works. Test that
  assumption per phase. Default to a **contextual bandit over config bundles**;
  escalate to GRPO/DAPO-style RL only when a phase's reward provably isn't
  greedy-decomposable. Cheaper, and it's the honest baseline.
- **B. Phase boundary definition.** Define phases **operationally** — explicit
  phase tags the agent emits, or a tool-use signature (search/read = localize;
  edit = repair). Treat boundary *detection accuracy* as a measured quantity,
  not an assumption. This converts the fuzzy-boundary risk into a reported
  result.
- **C. Reward design per phase, with anti-gaming.** Localization = Hit@k/MRR on
  gold files (watch for "localize everything" gaming → penalize precision).
  Repair = tests pass. Test-writing = mutation/coverage-style quality, not just
  "tests run." Heterogeneity is the point; design each verifier deliberately.
- **D. Harder task set.** The Tier-1 ablation saturated at 100%. Pull the
  10–25% baseline-pass-rate band (`results/swebench_lite_difficulty.csv`) so
  config choices actually move the reward.

---

## Positioning (how to talk about it)

Lead with the three deltas vs the nearest neighbors, every time:
1. **Verifiable** (not learned-surrogate) per-phase rewards — vs Optimas.
2. **Phase-keyed** (not arbitrary-graph) structure — vs Optimas/DSPy.
3. **Config bundle {model × prompt × context-strategy} as the action** — vs
   LLMSelector (model-only) and DSPy (prompt-only).

The one-sentence claim: *a per-phase policy over configuration bundles, trained
against verifiable phase rewards, with the handoff brief between phases as a
learnable context-strategy action.*

---

## What NOT to do
- Don't build all four phases at once — localization first, fully, then widen.
- Don't build Crab-level container C/R before cheap snapshots prove inadequate.
- Don't chase a full RL training loop before the bandit-over-configs result on
  localization lands.
- Don't cite projected/blog cost figures (Tool Attention, vendor numbers) as
  measured results.

---

## Backlog mapping (`NEXT.md`)
- **Handoff-as-routing (`#33`)** → becomes Step 3; no longer a separate thread.
- **Generalize `ContextPolicy` → `ContextEngineering`** → prerequisite for
  "context-strategy as action" (Steps 2–3); do it as part of Step 2.
- **Harder tasks for the ablation** → Decision D.
- **Persistent cost ledger / cold-warm cost / TTFT split** → still valuable as
  measurement, but secondary to landing Steps 0–2. Pick up opportunistically.
- **Populate `model_backends.yaml` empirically** → subsumed: the per-phase
  bandit *learns* this instead of guessing it.
