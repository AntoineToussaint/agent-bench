# Platform thesis: phased agents as per-phase RL environments

This is the deeper goal the bench is building toward. `NEXT.md` lists
incremental threads; `SOTA.md` anchors the context-engineering
literature. This file states the unifying research thesis and the
verified landscape around it.

All arxiv IDs below were abstract-page-verified on 2026-05-28
(title + ID + date). Unverified / non-arxiv items are marked.

---

## The thesis

A coding agent solving a task (e.g. a SWE-bench issue) runs through
**fixed phases**: localization → repair → test-writing →
verification. Make each phase a first-class object that is:

- **checkpointable** — run the agent, stop at a phase boundary, snapshot
  repo + container + history;
- **resettable** — `reset_to_phase_boundary()`, not just `reset()` to task
  start; fork N rollouts from the same post-localization state;
- **independently & heterogeneously rewardable** — localization Hit@k ≠
  repair test-pass ≠ test-quality. Different verifier per phase, not one
  terminal outcome reward;
- **configurable** — at each phase, choose {model, prompt template,
  context-engineering strategy}. Learn that choice per phase against the
  phase reward; don't hand-tune it.

So each phase is a `(state, action, reset, reward)` sub-environment, and
the **action space includes the meta-choice of configuration**. The bench
becomes an RL-environment generator + config-optimization substrate, not
just a measurement harness.

## Two tracks that solve each other's hard problem

**Track A — phase-segmented RL environment.** Checkpoint/fork at phase
boundaries; heterogeneous per-phase verifiable rewards; per-phase + end-to-end
RL.

**Track B — per-phase configuration policy.** A policy over
{model × prompt × context-strategy} bundles, conditioned on phase, learned
against the phase reward.

The leverage: **Track B's central pain is credit assignment across stages**
— every config-optimizer either collapses it to a global metric (DSPy/MIPRO)
or *learns a surrogate* local reward (Optimas) because a real one is
unavailable. **Track A hands you a ground-truth per-phase reward for free**,
eliminating the surrogate. Conversely, Track A's discrete verifiable
sub-episodes make a *bandit over configurations* tractable (no long-horizon
credit decay). They compose.

---

## Verified landscape — Track A (RL environment)

**RLVR for code (all use a single terminal reward over the full rollout):**
- DeepSeek-R1 — `2501.12948` — canonical RLVR recipe (GRPO, rule-based reward).
- SWE-RL — `2502.18449` — first RL for SE; patch-similarity reward; 41.0% SWE-bench Verified.
- Long-context multi-turn SWE agents w/ RL — `2508.03501` — RFT then DAPO; 11%→39% Pass@1. (Phasing is *training-pipeline*, not *trajectory*.)
- DeepSWE — Together AI **blog, no arxiv ID** — Qwen3-32B, RL-only over R2E-Gym.

**Process / step rewards:**
- Let's Verify Step by Step — `2305.20050` — process supervision > outcome supervision (founding PRM).
- iStar (implicit step rewards) — `2509.19199` — implicit per-step reward via trajectory-DPO; WebShop/Sokoban, **not code**.

**Gym-style resettable SWE envs (reset is task-granular, terminal reward only):**
- SWE-Gym — `2412.21139` — first SWE-agent training env; 2,438 real instances + trained verifiers.
- R2E-Gym — `2504.07164` — ~8.7K procedural tasks; hybrid verifiers; 51% SWE-bench Verified.

**Localization as a task (measured as a metric, almost never as an RL reward):**
- Agentless — `2407.01489` — names the exact phases (localize→repair→validate); 32% SWE-bench Lite, no agent loop.
- LocAgent — `2503.09089` — graph-guided localization; 92.7% file-level acc.
- RGFL — `2601.18044` — reasoning-guided fault localization; **counterfactual upper-bound quantifying each localization stage's contribution to repair** (closest thing to per-phase credit, but as analysis not reward).

**Per-phase / subgoal credit (exists, but learned subgoals + non-code):**
- HiPER — `2602.16165` — plan-execute hierarchy, unbiased variance-reducing hierarchical advantage; ALFWorld/WebShop, **not code**.

**Checkpoint / fork of agent state (turn-granular, semantics-agnostic):**
- Crab — `2604.28138` — eBPF C/R of container state at turn boundaries; explicitly lists "RL rollout branching"; recovery 8%→100%. The enabling substrate.
- Snapshot RL — `2403.00673` — mid-trajectory states as reset distribution (classical RL, not LLM/code).

## Verified landscape — Track B (configuration policy)

**Routing / model selection (per-query, single-axis arm):**
- RouteLLM — `2406.18665` — strong/weak router from preference data; >50% cost cut.
- FrugalGPT — `2305.05176` — LLM cascade; up to 98% cost reduction.
- Cascade routing — `2410.10347` — routing & cascading unified into one optimal policy.
- Routing survey — `2603.04445` — taxonomy of the routing/cascading landscape.

**Automatic prompt optimization (multi-stage exists; per-stage *verifiable* reward does not):**
- DSPy — `2310.03714` / MIPRO — `2406.11695` — optimizes prompts per module but credit = single **end-to-end** metric, bootstrapped from globally-successful traces. No per-stage reward, no model/context choice.
- GEPA — `2507.19457` — reflective/Pareto evolution; beats GRPO by 6% avg / up to 20% (v2 figures) at ~35× fewer rollouts. Current frontier; now a DSPy optimizer.
- TextGrad — `2406.07496` — textual-gradient backprop through compound systems.
- (also OPRO `2309.03409`, ProTeGi `2305.03495`, EvoPrompt `2309.08532`.)

**Adaptive context strategy (learnable, but only the retrieve-or-not axis):**
- Adaptive-RAG — `2403.14403` — classifier picks no/single/iterative retrieval by predicted complexity.
- Self-RAG — `2310.11511` — reflection tokens decide on-demand retrieval + self-critique.

**Bandits / RL over configs (arm is a model, never a bundle):**
- MAB-meets-LLM survey — `2505.13355`.
- Online multi-LLM selection via contextual bandits — `2506.17670` — LinUCB over models, **per-query**.

**Joint pipeline-level config optimization (the directly competitive cluster):**
- LLMSelector — `2502.14815` — per-module **model** selection via estimated per-module performance; assumes end-to-end monotonic in module quality (so greedy works). **Model only.**
- Optimas — `2507.03041` — **per-component learned local reward** aligned to global objective, then independent per-component config optimization. Closest prior art — but rewards are **learned surrogates** not verifiable, graph is arbitrary not phase-structured, and context-strategy isn't an action.
- MASPO — `2605.06623` — joint prompt optimization across multi-agent systems with successor-agent-success credit. **Prompts only.**

**Conditional materialization (the bun-vs-npm angle):**
- Tool Attention — `2604.21816` — intent-scoring + state-aware tool gating; ~95% schema-token cut (**numbers are projections, not live evals**).
- Self-RAG — `2310.11511` — conditional fact materialization.

**Live evidence the gap is real:** SGAgent — `2602.23647` — decomposes repair
into localizer→suggester→fixer but runs **one backbone across all three**
(Claude-4, 60.7%). Phase decomposition is already standard in shipped coding
agents; per-phase *configuration* is left on the table.

---

## The open gap (what no single paper does)

Nobody exposes localization/repair/test/verify as **checkpointable,
resettable, heterogeneously-rewarded** sub-environments AND optimizes the
**full {model × prompt × context-strategy} bundle per phase against
externally verifiable per-phase rewards**. Each near-neighbor falls short on
one defensible axis:

- DSPy/MIPRO: prompt-only, global metric, no model/context choice.
- LLMSelector: model-only, *estimated* (not verifiable) reward.
- Optimas: heterogeneous config but *learned surrogate* reward, arbitrary
  graph (not phase-structured), no context-strategy action.
- Routing/bandits: per-query, single-axis arm.
- Crab: turn-granular, semantics-agnostic checkpoints, not wired to rewards.

### Sharpest defensible novelty
Cast each phase as a contextual-bandit / short-horizon RL problem whose **arm
is the configuration bundle** and whose **reward is the phase's own verifiable
checkpoint signal** — turning the phase-segmented environment into the
credit-assignment mechanism every config-optimizer had to fake.

The most ownable sub-claim: **the handoff brief between phases is itself a
learnable context-strategy action** — learn *what compressed context to pass
from localization into repair*, rewarded by the repair phase's verifier. This
is exactly where "context-strategy as action" meets "per-phase verifiable
reward," and it sits in no existing paper's scope. It also closes the
handoff-as-routing thread in `NEXT.md`.

---

## Read first

1. **Optimas (`2507.03041`)** — closest prior art. Be able to articulate the
   delta: verifiable (not surrogate) rewards, phase-keyed (not arbitrary-graph)
   structure, context-strategy as an action.
2. **LLMSelector (`2502.14815`)** — cleanest per-module-model-selection
   statement; its monotonicity assumption decides whether you need full RL or
   just greedy/bandit allocation per phase.
3. **MIPRO (`2406.11695`)** — the precise account of what DSPy does, so you can
   correctly say it has no per-stage verifiable reward and no model/context
   selection. Your cleanest differentiator vs the most-cited baseline.
4. **Agentless (`2407.01489`)** — already names your phases; your strawman and
   scaffolding. See exactly where it stops (no reset, no per-phase reward).
5. **Crab (`2604.28138`)** — the checkpoint/fork substrate; don't rebuild the
   systems plumbing.

## Honest caveats
- The field is moving fast — several of the most-relevant papers are Jan–Apr
  2026. The modular pieces are all on the table; someone could glue a
  "phase-aware SWE-Gym" within a quarter. The moat is the
  *heterogeneous-verifiable-reward-per-phase* + *config-bundle-as-action*
  framing, not the phase decomposition itself (Agentless owns that).
- **Phase boundaries are fuzzy** — real agents interleave localization and
  repair. "Where does a phase end?" is itself a research question the bench
  must answer, not assume.
- Tool Attention's and various vendor cost figures are projections / blog
  claims, not live evals — don't cite as measured results.
