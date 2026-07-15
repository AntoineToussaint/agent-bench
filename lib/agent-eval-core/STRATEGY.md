# Strategy

> New here or coming back after a break? Read the [root
> README](../../README.md) first — it explains in plain English *what we're
> building and why* before this doc gets into the *how*.

The plan of record. `PLATFORM.md` argues the thesis and cites the
verified landscape; `SOTA.md` anchors the context-engineering
literature; `NEXT.md` is the backlog. This file says **where we are**,
**what we're optimizing for**, and **what to do in what order, and why**.

> **2026-07-15 reset:** the detailed audit and current literature comparison is
> in [`REVIEW_2026-07-15.md`](REVIEW_2026-07-15.md). It supersedes older claims
> that per-phase selection is an unoccupied niche. The immediate gate is now a
> same-model comparison of a minimal free loop, fixed phases, and an adaptive
> workflow. Do not build a bandit before that scaffold-value result.

---

## Objective

**Earn the scaffold before optimizing it.** Build the smallest end-to-end agent,
then test whether fixed or adaptive phase control improves on a pinned minimal
free-loop baseline under the same model and budget. Per-phase configuration
optimization is a refinement layer applied *after* a scaffold works and proves
its value. The defensible research claims (vs Optimas / LLMSelector / DSPy) are a
byproduct of building the platform well, not the thing that drives
sequencing. Practical consequence: prioritize a system that solves tasks
end-to-end over a narrow publishable slice.

---

## Where we are

**The instrument (built over prior sessions; ~30 commits):**
- Unified `ModelHandle + ToolBackend + OTEL` substrate across Anthropic /
  OpenAI / Google clients; pricing + backend YAML wired.
- Failure-mode classifier; `DIMENSIONS.md` / `HARNESS.md` / `FAILURE_MODES.md`
  position the bench against SOTA.
- Tier-1 context engineering: `ContextPolicy` abstraction + 3 policies. First
  ablation: `ToolResultElision` cut cost 45% at unchanged accuracy on 3
  astropy tasks — but all 3 policies passed 100%, so the task set is too easy
  to differentiate (a known limitation; see Decision D).
- Gate 1 now has a hermetic end-to-end pilot harness in `experiments/code-editing`:
  a versioned minimal free loop, enforced fixed phases, and a frozen adaptive
  heuristic share one model/tool/oracle/turn-cap contract. Offline scripted
  tests and a no-client dry run pass. This validates execution and paired
  reporting; it is not yet the official mini-SWE-agent/SWE-bench comparison.

**The hypothesis (see `PLATFORM.md`):**
A coding agent may benefit from explicit phases — localization → repair →
test-writing → verification. Make each candidate phase a checkpointable, resettable,
**heterogeneously-rewardable** sub-environment whose **action space includes
the config bundle {model × prompt × context-strategy}**, learned per-phase
against a verifiable phase reward.

**Why this remains a plausible bet:** the config-optimization literature's central
pain is per-stage credit assignment — DSPy collapses it to a global metric,
Optimas *learns a surrogate* local reward because a real one is unavailable. A
phase-segmented environment supplies a measurable per-phase reward (with the
big caveat below). The neighborhood is now crowded: Optimas optimizes
heterogeneous components with aligned local rewards; LLMSelector chooses models
per module; Atalar et al. (`2508.09958`) apply a contextual bandit to dependent
LLM pipelines; and icat-agent (`2606.25514`) adaptively chooses issue-resolution
workflows. The narrower open question is whether **joint model × prompt ×
context/handoff routing at verifiable SWE boundaries** generalizes on held-out
repositories and improves downstream resolution.

---

## The reward reality (read before believing "free reward")

The "ground-truth per-phase reward for free" claim is **only partly true, and
the split matters more than anything else in this doc.**

| phase reward | available at deploy time? |
|---|---|
| repair: tests pass | **Yes** — you can run tests on any task |
| localization: Hit@k vs gold files | **No** — gold files exist only on labeled benchmarks |
| test-quality vs gold | **No** — oracle-only |

So the rewards split into **prod-available** (test execution) and
**oracle-only** (anything compared to a gold patch). The localization reward —
the one we lean on first because it's "cleanest" — **does not exist in
production**, which is the whole point of a coding agent: you don't know the
answer.

**The bridge:** train the per-phase config policy **offline** on labeled tasks
(SWE-bench, where oracle rewards exist), then **deploy the frozen policy**. The
open question this raises — and a genuine research contribution if answered —
is **transfer**: does a config policy learned on the SWE-bench distribution
hold on the platform's real task distribution? Treat this as a first-class
question, not a footnote.

Corollary: also a noisy-proxy problem. The gold patch is *one* valid fix site;
rewarding localization Hit@k against it penalizes valid alternative
localizations. Use it as a training signal, not ground truth about "good
localization."

---

## Strategy: phase-capable substrate, scaffold comparison, then optimize

Build the smallest end-to-end agent and the ability to mark/enforce phase
boundaries. Each step is a platform capability that also yields a result.

### Step 0 — Phase substrate: enforce, checkpoint, reward
Two coupled pieces of new infra everything needs:
- **Phase-capable control.** Implement a driven sequence in which localize emits
  structured candidates before repair, test, and verify, while retaining a
  free-loop path and an adaptive path. This makes enforcement an experimental
  arm and still gives every treatment the same trace/checkpoint vocabulary.
- **`reset_to_phase_boundary(state)` + per-phase reward hook.** Snapshot/restore
  repo + conversation + tool state at a phase edge. Build cheap first
  (git-state + serialized conversation), adopt Crab-style (`2604.28138`)
  container C/R only if cheap snapshots prove insufficient. Reuse existing
  OTEL + `ToolBackend`. **The interface spec for this is `TRACE.md`** — the
  `PhaseNode` two-plane (conversation / environment) data model. Localization
  is read-only so its `env_ref` is null: the whole loop validates on just a
  serialized conversation, no snapshot infra.

### Step 1 — End-to-end scaffold-value experiment
Build full task resolution and compare three arms with the same backbone,
reasoning setting, budget, environment, and tasks: **(a) a pinned mini-style
free loop, (b) fixed localize → repair → test → verify phases, and (c) an
adaptive workflow driven only by deploy-time issue/state features.** Reproduce
Agentless (`2407.01489`) localization as a component baseline. Deliverable: the
platform solves tasks end-to-end, can stop/checkpoint/score at phase boundaries,
and shows whether phase control earns its complexity. If the minimal loop wins,
retain phase boundaries as trace annotations rather than forced control flow.

### Step 2 — Reward alignment, then per-phase config selection
Vary {model × prompt × context-strategy} per phase; select per phase against
the phase reward. **Headline comparison: does per-phase config selection beat
the best single config?** That result matters for the platform (a better,
cheaper agent) and is the most compelling research claim — and it's available
here, not at Step 4.

First validate that improving each phase reward predicts downstream resolution
by forking from identical checkpoints. Then make routing tractable (Decision A
+ C):
- **Prune the arm.** {model × prompt × strategy} at 5×5×5 = 125 arms × expensive
  rollouts is infeasible. Cut to 2–3 options per axis; the *interaction* between
  axes (a strong model wants a different context strategy than a cheap one) is
  the novelty, so don't factorize the axes away — shrink them instead.
- **Separate the baselines.** `config = f(phase)` is a static heterogeneous
  table. A contextual router is `config = f(phase, task, state)` and must be
  selected/tuned on train/validation repositories, then reported on held-out
  repositories. Keep the per-task reward oracle only as an upper bound.
- **Contextual bandit, not full RL**, with phase plus deploy-time task/state
  features as context. Escalate
  to GRPO/DAPO-style RL only if a phase's reward provably isn't
  greedy-decomposable (test LLMSelector's monotonicity assumption, `2502.14815`).
- Train offline on oracle rewards; this is where the localization reward earns
  its keep (see "reward reality").

### Step 3 — Handoff brief as a learnable context-strategy action
Fork from the post-localization checkpoint; learn *what compressed context to
pass into repair*; reward by the repair phase's verifier (which is
**prod-available** — tests pass — so this one survives deployment). The single
most ownable research sub-claim, and a real platform capability (smarter
inter-phase context). Closes the handoff-as-routing thread in `NEXT.md`. The
bun-vs-npm example is the verifiable testbed for the gating variant.

### Step 4 — Science depth (optional, secondary)
Whether phase-local rewards reduce the credit-assignment variance that
iStar/HiPER complain about. Genuine science, but it does not gate the platform
and is no longer the headline — Step 2's beats-best-single-config is. Pursue
only if the platform is solid and a deeper paper is wanted.

---

## Decisions to make early (don't drift on these)

- **A. Bandit vs full RL.** Default to a **contextual bandit over (pruned)
  config bundles**, using phase plus deploy-time task/state features. Treat
  phase-only selection as the static-table baseline. Escalate to RL only when a
  phase's reward isn't greedy-decomposable (LLMSelector `2502.14815`
  monotonicity). Cheaper, honest baseline.
- **B. Phase boundaries — an experimental arm, not an assumption.** Implement
  architecturally enforced boundaries with structured outputs, but compare them
  to a pinned free loop and an adaptive workflow. This isolates the value and
  cost of driven phase control instead of accepting it by construction.
- **C. Reward design, granularity, anti-gaming.** Localization: target
  **element/line level**, not file level — file-level is ~93% solved (LocAgent)
  and will saturate like the Tier-1 ablation did; element-level has headroom
  (RGFL: Exact@top-3 36→69%). Penalize precision to stop "localize everything"
  gaming. Repair: tests pass. Test-writing: mutation/coverage quality, not just
  "tests run."
- **D. Harder task set.** Pull the 10–25% baseline-pass band
  (`results/swebench_lite_difficulty.csv`) so config choices actually move the
  reward.
- **E. Reward availability (the train/deploy split).** Be explicit per phase
  about prod-available vs oracle-only rewards (see "reward reality"). Build the
  offline-train / deploy-frozen path, and measure transfer.

---

## Positioning (the research byproduct)

If/when written up, lead with the three deltas vs nearest neighbors:
1. **Verifiable** (not learned-surrogate) per-phase rewards — vs Optimas.
2. **Phase-keyed** (not arbitrary-graph) structure — vs Optimas/DSPy.
3. **Config bundle {model × prompt × context-strategy} as the action** — vs
   LLMSelector (model-only) and DSPy (prompt-only).

One-sentence claim: *a per-phase policy over configuration bundles, trained
against verifiable phase rewards, with the handoff brief between phases as a
learnable context-strategy action.* The transfer question (offline-trained
policy → real task distribution) is the honest open problem and a contribution
if answered.

Note on the "window": because the objective is platform-first, scoop risk
matters less than it would for a paper-first plan. The working system is the
moat; a competing arxiv preprint doesn't erase a deployed platform.

---

## What NOT to do
- Don't optimize configs before the end-to-end pipeline (Step 1) works.
- Don't claim scaffold gains without the pinned minimal free-loop control.
- Don't call an in-sample taskwise oracle a selector or routing result.
- Don't call phase identity alone “contextual” routing; it yields a static table.
- Don't build the full 125-arm config space — prune to 2–3 per axis.
- Don't build Crab-level container C/R before cheap snapshots prove inadequate.
- Don't treat localization Hit@k as deployment-time signal or as ground truth
  about good localization — it's an offline training proxy.
- Don't cite projected/blog cost figures (Tool Attention, vendor numbers) as
  measured results.

---

## Backlog mapping (`NEXT.md`)
- **Handoff-as-routing (`#33`)** → Step 3.
- **Generalize `ContextPolicy` → `ContextEngineering`** → prerequisite for
  "context-strategy as action"; do it as part of Step 2.
- **Harder tasks for the ablation** → Decision D.
- **Persistent cost ledger / cold-warm cost / TTFT split** → measurement, useful
  for the platform's cost story; pick up opportunistically alongside Step 1.
- **Populate `model_backends.yaml` empirically** → subsumed: the per-phase
  bandit *learns* this instead of guessing it.
