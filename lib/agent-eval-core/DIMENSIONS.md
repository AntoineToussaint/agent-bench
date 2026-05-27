# Capability dimensions

What this bench measures, what it doesn't, and where it sits relative to
the broader agent-benchmark landscape.

## What we measure today

Three experiments, three dimensions. All scored uniformly via
`RunRecord.passed: bool` with experiment-specific secondary metrics
on `RunRecord.extra`.

| dimension | experiment | primary metric | RunRecord.passed when |
|---|---|---|---|
| **find** (localize) | `file-localization` | recall on gold source files | `recall == 1.0` (test files filtered before scoring) |
| **plan** (tool-use) | `tool-selection`   | `ScoreCard.task_success`     | selection ✓ AND args ✓ AND no forbidden/hallucinated AND all required calls present |
| **edit** (code)     | `code-editing`     | oracle exit code             | `oracle_cmd` returns 0 against merged workdir + hidden test overlay |

### Common columns (every RunRecord, every experiment)

- `passed: bool` — the headline metric
- `turns`, `tool_calls`, `invalid_tool_calls`
- `usage` — input / output / cache-read / cache-creation tokens
- `latency_seconds`, `cost_usd`
- `error` — set on hard failure (e.g. "aborted: 3 consecutive error turns")
- `extra["failure_mode"]` — one of the 17 categories from `FAILURE_MODES.md`

### Per-experiment extras

- **find**: `recall`, `precision`, `f1`, `n_predicted`, `n_false_positives`, `composite` (= recall − fp_penalty·fp/|gold|), `submitted`, `observed_paths`, `done_called`, `unique_signatures`, `mimicry_attempts`, `backend`
- **plan**: `selection_matched`, `selection_accuracy`, `args_accuracy_given_selection`, `required_total`, `required_matched`, `missing_required`, `extras_called`, `hallucinated`, `forbidden_called`, `schema_invalid`, `approach_id`, `granularity`, `surfaced_count`, `n_calls`
- **edit**: `write_attempts`, transcript path, stdout/stderr from oracle

### Single-number scorecard

`scripts/run_all_experiments.py` reduces the three dimensions to a
one-page report:

```
| capability         |  n | pass | cost     | latency |
| find  (localize)   |  3 | 100% | $0.0512  |  13.7s  |
| plan  (tool-use)   |  3 | 100% | $0.0010  |   1.3s  |
| edit  (code)       |  3 | 100% | $0.0139  |   7.1s  |
```

Same model, three capabilities. No aggregation across rows — they
measure different things in different units.

## What we don't measure (and where the published field stands)

A quick map of the agent-benchmark landscape and where we sit. Survey
citations in the references at the bottom.

### Well-served by existing benchmarks (not our fight)

| dimension | canonical benchmark | what they do |
|---|---|---|
| End-to-end SWE-Bench (localize + edit + verify integrated) | [SWE-Bench Verified / Lite / Pro](https://www.swebench.com/) [1] | pass-rate on real GitHub issues |
| Web navigation / interactive browsing | [WebArena](https://webarena.dev/), [VisualWebArena](https://jykoh.com/vwa) | long-horizon multi-page nav with execution-based success |
| OS / desktop control | [OSWorld](https://os-world.github.io/), [WindowsAgentArena](https://microsoft.github.io/WindowsAgentArena/) | full mouse/keyboard control across apps |
| Autonomous ML R&D | [MLE-Bench](https://arxiv.org/abs/2410.07095), [MLAgentBench](https://arxiv.org/pdf/2310.03302), [RE-Bench](https://arxiv.org/pdf/2411.15114) | model training, kernel opt, scaling-law fitting; scored vs Kaggle medals or human-expert time |
| Function-calling AST correctness | [BFCL v4](https://gorilla.cs.berkeley.edu/leaderboard.html), [ToolBench](https://www.emergentmind.com/topics/toolbench) | parallel/multiple call structures, AST-match scoring |
| Generic agent environments | [AgentBench](https://arxiv.org/abs/2308.03688) (Liu et al.) | 8 distinct environments (OS shell, DB, KG, card game, …) |
| Open-ended multi-step reasoning + retrieval | [GAIA](https://arxiv.org/abs/2311.12983) | 466 real-world questions, 3 difficulty levels |

We *intentionally* don't aim at any of these — they have stronger
infrastructure and entrenched leaderboards.

### Underserved and a plausible fit for our stack

| dimension | what it asks | published prior art | gap |
|---|---|---|---|
| **clarify** | given an ambiguous coding task, does the agent ask before acting? | [τ-bench](https://arxiv.org/abs/2406.12045) does this for retail / airline domains | nothing canonical for *coding* tasks (`τ-coding` doesn't exist) |
| **review** | given code + change, can the agent critique without editing? | [CodeCriticBench](https://arxiv.org/html/2502.16614v1) exists but is small and not integrated with localize / edit | rarely scored *alongside* find/plan/edit on the same task pool |
| **comprehend** | explain / Q&A over real repos without editing | [CoReQA](https://arxiv.org/pdf/2501.03447), [CRUXEval](https://arxiv.org/pdf/2505.05283) | not unified with our find / edit corpora |
| **abstain** | should the agent call any tool at all? | [MetaTool](https://arxiv.org/html/2310.03128v4), BFCL "relevance" | not part of our tool-selection trial today |
| **consistency** | pass^k across repeated trials, not just pass@1 | τ-bench's `pass^k`, RE-bench | we have `repetitions` in `Sweep` but no `pass^k`-style metric yet |
| **policy adherence** | obey explicit constraints (e.g. "don't write files outside repo") | τ-bench (business rules), IFEval-FC | code-editing has it implicitly via fixtures; not measured separately |

### Where we appear uniquely positioned

The agent that did the survey called out one gap as **unclaimed** in
published work:

> **Per-(model, task-type) backend/protocol recommendations backed by
> cross-experiment failure-mode classification.**

[MAST](https://arxiv.org/abs/2503.13657) and Microsoft's [Taxonomy of
Failure Modes in Agentic AI](https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/microsoft/final/en-us/microsoft-brand/documents/Taxonomy-of-Failure-Mode-in-Agentic-AI-Systems-Whitepaper.pdf)
catalog failures. [ToolScan](https://arxiv.org/html/2411.13547v2) and
["Teaching a LM to speak the language of tools"](https://arxiv.org/pdf/2506.23394)
study format sensitivity. **None closes the loop to**:

> *"Therefore, when running model M on task type T, use protocol P; here
> are the empirical pass-rate / cost / failure-mode numbers backing that
> recommendation."*

That closed loop is the differentiator. `model_backends.yaml` +
`FAILURE_MODES.md` + the `classify_*` functions are the pieces; what's
missing is more coverage (more models, more task types).

## Concrete next-step proposals, ranked

1. **Coverage of the existing 3 dimensions** — populate `model_backends.yaml` empirically for more models (Opus 4.7, GPT-5, plus the now-wired Gemini 2.5 Pro / Flash-Lite). Currently 3 of 9 entries have empirical backing (Haiku, Sonnet, and Flash from the 3-lab smoke).
2. **Split `latency_seconds` into TTFT + generate** — switch all three model clients (Anthropic, OpenAI, Google) from non-streaming `create` to streaming `stream`, capture monotonic timestamp at first content delta. New `TurnUsage.ttft_seconds` / `generate_seconds` fields. Pairs with `batch_efficiency`: a chatty model with high TTFT pays the start-up cost every turn. ~1-2 hours, all infrastructure already in place.
3. **Add `abstain`** to tool-selection — small change to the existing scorer; just need tasks where the right answer is "call nothing." Closes a published gap (MetaTool, BFCL) inside our existing harness.
4. **Add `consistency`** — derived metric, not a new experiment. Run any cell at `repetitions=5+`, report `pass^k` and `pass@1` side-by-side. Free with what we have.
5. **Add `clarify`** — new experiment, but reuses everything: a user-simulator (cheap LLM) replies to agent questions; score = ambiguity resolved before acting. Closes a real gap (no `τ-coding` exists).
6. **Add `review`** — wrap [CodeCriticBench](https://arxiv.org/html/2502.16614v1) tasks as a fourth experiment. Lift their dataset; same `(handle, condition, task) → RunRecord` shape.

(1)–(4) are pure data-collection, one-line metric changes, or
infrastructure refinements — small work, real value. (5)–(6) are new
experiments — bigger, also novel.

## References

[1] [SWE-Bench leaderboards](https://www.swebench.com/) · [SWE-Bench Pro](https://www.morphllm.com/swe-bench-pro) · [SWE-Bench Multimodal](https://arxiv.org/abs/2410.03859)

Tool calling: [BFCL v4](https://openreview.net/forum?id=2GmDdhBdDk) · [MetaTool](https://arxiv.org/html/2310.03128v4) · [ToolScan](https://arxiv.org/html/2411.13547v2) · [IFEval-FC](https://arxiv.org/pdf/2509.18420) · ["Teaching a LM to speak the language of tools"](https://arxiv.org/pdf/2506.23394)

Dialogue / multi-turn: [τ-bench](https://arxiv.org/abs/2406.12045) · [tau2-bench](https://github.com/sierra-research/tau2-bench)

Code comprehension: [CRUXEval](https://arxiv.org/pdf/2505.05283) · [CoReQA](https://arxiv.org/pdf/2501.03447) · [CodeQA](https://aclanthology.org/2021.findings-emnlp.223/) · [CodeCriticBench](https://arxiv.org/html/2502.16614v1)

ML R&D agents: [MLE-Bench](https://arxiv.org/abs/2410.07095) · [MLAgentBench](https://arxiv.org/pdf/2310.03302) · [RE-Bench](https://arxiv.org/pdf/2411.15114)

Web / OS: [WebArena](https://webarena.dev/) · [VisualWebArena](https://jykoh.com/vwa) · [OSWorld](https://os-world.github.io/) · [WindowsAgentArena](https://microsoft.github.io/WindowsAgentArena/)

Generic / multi-domain: [AgentBench](https://arxiv.org/abs/2308.03688) · [GAIA](https://arxiv.org/abs/2311.12983)

Failure-mode taxonomies: [MAST](https://arxiv.org/abs/2503.13657) · [Microsoft Taxonomy of Failure Modes in Agentic AI](https://cdn-dynmedia-1.microsoft.com/is/content/microsoftcorp/microsoft/final/en-us/microsoft-brand/documents/Taxonomy-of-Failure-Mode-in-Agentic-AI-Systems-Whitepaper.pdf) · ["Empirical study of failures in automated issue solving"](https://arxiv.org/pdf/2509.13941)
