# LLM Agent Failure Modes

A taxonomy of how LLM agents fail at code-localization (and more broadly,
tool-using tasks). Grounded in the literature, refined by observations
from this repo's runs.

## Why this document exists

We needed a vocabulary for diagnosing trial failures. Saying "the model
gave a wrong answer" doesn't help us choose between *prompt fixes*,
*protocol changes*, *escape-valve tuning*, or *task-design changes* —
each addresses a different failure class.

A named taxonomy lets us:

- Compare runs across model × protocol cells with a common diagnostic
  vocabulary.
- Build failure-class-specific detectors (in `agent_eval.failure_modes`)
  so new trial records get classified automatically.
- Export test fixtures: *here is a task that reliably triggers
  Path Fabrication on Haiku × PromptJSON — does YOUR agent fall into
  the same trap?*

## The tree

The taxonomy is an explicit tree in `agent_eval.failure_modes.TAXONOMY`
(category → {leaf mode: description}). The flat `FailureMode` strings stay the
return/wire type; the tree is the structure over them. `category_of(mode)` and
`taxonomy_path(mode)` look a mode up; group failures by category for reporting.

```
localization     missed/mislocated the files to edit
  ├── localization_missing       found some gold, missed the rest (recall < 1)
  ├── localization_irrelevant    zero gold hits — wrong region entirely
  ├── localization_too_many      found all gold but buried in false positives
  ├── path_fabrication           predicted a path never observed in the repo
  └── superficial_information_matching  matched issue keywords to filenames
memory
  └── context_amnesia            lost earlier context / repeated known work
process          had the info, used it wrong
  ├── step_repetition · premature_termination
  └── reasoning_action_mismatch · blind_strategy_switching
protocol         harness/protocol blocked success regardless of model
  └── format_anchoring · harness_blocked_termination · harness_blocked_exploration
tool_selection   (catalog tasks)  hallucinated_tool · wrong_tool_selected · missing_required_call · forbidden_tool_called
code_editing     (edit-until-tests-pass)  oracle_failed · read_only_loop · edit_apply_error
```

The `localization_*` leaves answer *which way* localization failed — the
"missing / too many / irrelevant" distinction — via
`classify_localization(predicted, gold)`. They're localization-specific; the
rest of the `localization` category and the other categories are shared across
experiment shapes.

## Reading guide

The taxonomy groups leaf modes into the categories above (originally framed as
5 tiers):

1. **Information failures** (3) — model failed to *acquire* the correct
   information needed to answer.
2. **Process failures** (4) — model had the information but failed to
   *use* it correctly (loops, mismatches, premature commits).
3. **Protocol failures** (3) — the harness/protocol design prevented
   success irrespective of model quality.
4. **Tool-selection-specific** (4) — for trials where the task is
   "pick + invoke the right tools from a catalog."
5. **Code-editing-specific** (3) — for trials where the task is "make
   code changes until tests pass."

Tiers 1-3 are universal across agentic tasks; tiers 4-5 only fire for
their respective experiment shape. The relevant classifier knows which
tier(s) apply.

Each entry below has: a one-line definition, the signals that detect it,
an observed example (where available), and a citation. Citations point
at the literature row where the category was named — see References.

---

## Tier 1: Information failures

### `path_fabrication`

The agent submits a path it never observed during exploration. Closely
related: API/argument/file fabrication.

- **Signal**: predicted file ∉ paths the agent visited (via `view_file`,
  `grep`, `list_files`, or equivalent).
- **Example**: Haiku × PromptJSON × astropy-14995 (`results/protocol_matrix_v2/`).
  Mimicry blocked turn 1; on turn 2 the agent submitted
  `astropy/nddata/arithmetic.py` — a path that doesn't exist (real path:
  `astropy/nddata/mixins/ndarithmetic.py`) and which the agent never
  view_file'd.
- **Citation**: MIRAGE-Bench [4], "Butterfly Effects in Toolchains" [5].

### `superficial_information_matching`

Agent picks a wrong file because its name shares a token with the issue,
rather than because its contents are relevant.

- **Signal**: predicted file name contains a substring from the issue
  text but the file is NOT in the gold set; harder to detect
  automatically without a "near miss" notion.
- **Example**: not directly observed in our runs but a strong candidate
  for what Haiku × one-shot × astropy-14995 produced. Issue mentions
  "NDDataRef"; the actual gold file is `ndarithmetic.py` — a one-shot
  agent that hasn't read the repo plausibly emits `nddata.py` or
  `ndref.py` instead.
- **Citation**: Empirical SWE study [2], category A2.

### `context_amnesia`

Agent observed a fact in an earlier turn but ignores it in a later
turn's reasoning.

- **Signal**: gold path appears in the content of an earlier tool result,
  but the final submission doesn't include it.
- **Example**: not observed yet in our runs. Surfaces in long-context
  trials (turns > 10).
- **Citation**: Empirical SWE study [2], category C3.

---

## Tier 2: Process failures

### `step_repetition`

Same `(tool, args)` signature emitted on two or more consecutive turns,
producing no new information.

- **Signal**: at least 2 consecutive turns where the per-turn
  `new_signature` attribute is False.
- **Example**: Sonnet × Schema × astropy-12907. Turns 11-13 hammered
  `view_file(separable.py, [244, 248])` identically; the loop's
  `max_no_progress_turns=4` escape valve aborted on turn 14.
- **Citation**: MAST FM-1.3 [1]; also called "Non-Progressive Iteration"
  (Empirical SWE C2.1) and "Degeneration Loops" elsewhere.

### `premature_termination`

Agent calls `done` (or equivalent) before it has gathered enough
evidence to answer.

- **Signal**: trial finished within ≤2 turns AND tool_calls before
  `done` < 2 AND recall < 1.
- **Example**: Sonnet × PromptJSON × astropy-14995 (an earlier
  `results/cmp_14995_sonnet/` run). Agent emitted `done: true` on turn 1
  with hallucinated paths after 25s of "thinking" — but zero
  exploration.
- **Citation**: MAST FM-3.1 [1] (exact name match).

### `reasoning_action_mismatch`

Agent's text reasoning describes one intent but the executed action
does something different.

- **Signal**: assistant text mentions a specific path/symbol/tool but
  the next tool call uses a different one. Hard to detect purely
  programmatically; usually surfaces in narration around tool_use.
- **Example**: Sonnet × PromptJSON × astropy-14995 (cmp_14995_sonnet)
  emitted text like "I'll look at ndarithmetic.py" then submitted
  `arithmetic.py` (lost the `nd` prefix).
- **Citation**: MAST FM-2.6 [1]; "Say One Thing, Do Another" [9] is
  the canonical paper on the reasoning-execution gap.

### `blind_strategy_switching`

Agent flips strategy between turns without an explicit reason to do
so — e.g. switches from grep to view_file without having learned
anything.

- **Signal**: per-turn intent transitions that don't reference what was
  learned the previous turn. Requires reasoning-text analysis.
- **Example**: not observed in our runs yet.
- **Citation**: Empirical SWE study [2], category C2.2.

---

## Tier 3: Protocol failures

These are the *harness's* fault, not the model's. The model may have
been capable; the protocol design made success impossible.

### `format_anchoring`

Model emits the provider's native tool-call syntax (`<function_calls>`,
`<invoke>`) instead of the requested protocol format. The model has
been RL'd so heavily on the native format that prompt-based instruction
to use a different format is overridden.

- **Signal**: `<function_calls>` opening tag present in raw model output
  when running a prompt-based protocol (e.g. PromptJSONBackend).
- **Example**: Haiku × PromptJSON × astropy-14995. Turn 1 produced 11
  `<function_calls>` blocks (RL prior leakage); harness rejected them.
  Turn 2 produced 1 more. Turn 3 the agent gave up and hallucinated.
- **Citation**: novel; closest published analog is AgentBench's
  **Invalid Format (IF)** [3]. Related: Tam et al. finding that
  schema-constrained JSON output degrades accuracy ~27 pp.

### `harness_blocked_termination`

Protocol prevents the agent from ever calling its `done` tool, even
when it has gathered the answer. Most common cause: `tool_choice=any`
forces a non-`done` tool every turn.

- **Signal**: turn cap reached without a `done` call; possibly combined
  with thrashing (the agent ran out of new things to do).
- **Example**: Sonnet × Schema × astropy-12907. The agent did 10 turns
  of productive exploration then hit step_repetition because there was
  no legal way to stop.
- **Citation**: inverse of MAST FM-1.5 ("Unaware of Termination
  Conditions") [1]; here, the agent IS aware but is BLOCKED from
  acting on the awareness. Frame as harness-induced.

### `harness_blocked_exploration`

Protocol provides no tools at all (one-shot), so an answer that
requires exploration is unreachable.

- **Signal**: condition uses no tool channel AND recall < 1 AND the
  task requires information not in the issue text.
- **Example**: Haiku × one-shot × astropy-14995. The gold path
  `astropy/nddata/mixins/ndarithmetic.py` isn't named in the issue;
  one-shot can't reach it.
- **Citation**: degenerate sub-case of MAST's information-acquisition
  failures [1].

---

## Tier 4: Tool-selection-specific

These apply when the trial is "given a catalog of tools and a task,
emit the right calls in the right order." Diagnosed by
`classify_tool_selection(...)` from `tool_selection.types.ScoreCard`
fields.

### `hallucinated_tool`

The agent called a tool that doesn't exist in the surfaced catalog.

- **Signal**: `ScoreCard.hallucinated_calls` non-empty.
- **Example**: surfaced catalog has `git_commit`; agent called
  `git_create_commit`. Common when an agent confuses one provider's
  tool conventions with another's.
- **Citation**: MIRAGE-Bench [4] (tool fabrication); also called
  "API hallucination" in Winston & Just [6].

### `wrong_tool_selected`

The agent called a real tool from the catalog, but not the gold one.
Usually a confusable-siblings problem: picked `git_push` when the
task wanted `git_push_force`, or `gh_pr_comment` when the task
wanted `gh_pr_review_comment`.

- **Signal**: `ScoreCard.selection_matched == False` AND no
  hallucinated/forbidden calls (so the failure isn't worse-classed
  above).
- **Example**: routine in tool-selection's `1phase` runs against the
  `narrow` catalog when sibling-disambiguation is off.
- **Citation**: TRAJECT-Bench (sibling-tool selection); MAST FM-2.6
  (reasoning-action mismatch — a related shape).

### `missing_required_call`

The agent emitted some of the required calls but not all. The order
may still be correct; one or more required steps were omitted.

- **Signal**: `ScoreCard.missing_required` non-empty, selection_matched
  is true for the calls that DID happen.
- **Example**: task required `git_add` then `git_commit`; agent emitted
  only `git_commit`. (Models with weak plan-execution discipline drop
  the staging step.)
- **Citation**: maps to "incomplete completion" in the SWE-Bench-style
  empirical study [2].

### `forbidden_tool_called`

The agent invoked a tool the task explicitly forbids (e.g. the task
says "do not write" and the agent called `write_file`).

- **Signal**: `ScoreCard.forbidden_called` non-empty.
- **Example**: a "read-only inspection" task where the agent went
  ahead and modified state anyway.
- **Citation**: closely related to MAST FM-1.4 (constraint violation).

---

## Tier 5: Code-editing-specific

These apply when the trial is "given a task and starter files, edit
the code until an oracle test command passes." Diagnosed by
`classify_code_editing(...)`. Precedence is: `edit_apply_error` (the
format physically rejected every write attempt) > `read_only_loop`
(agent never tried to write) > `oracle_failed` (writes happened but
tests didn't pass).

### `oracle_failed`

The agent's edits applied successfully, but the oracle test command
returned non-zero. The code changed; the change was wrong.

- **Signal**: `oracle.passed == False` AND `write_attempts > 0` AND
  `invalid_tool_calls < write_attempts`.
- **Example**: agent edited the named function but with the wrong
  fix, or edited the right line in the wrong direction. This is the
  most common "real bug not fixed" failure.
- **Citation**: maps to "repair phase" failures in the empirical SWE
  study [2].

### `read_only_loop`

The agent made tool calls but never attempted any write — just
`view_file` / `list_files` until termination.

- **Signal**: `tool_calls > 0` AND `write_attempts == 0`.
- **Example**: Haiku occasionally on hard tasks: explores the
  codebase, never commits to an edit, calls `done` having done
  nothing. Related to `premature_termination` but specifically
  diagnosable when the trial offers writes and the agent declines
  them.
- **Citation**: a code-editing-specific instance of MAST FM-3.1
  (premature termination).

### `edit_apply_error`

Every write the agent attempted was rejected by the format's
applier — e.g. `search_replace` couldn't find the `old_str`, the
unified diff didn't match context, the semantic op named a symbol
that doesn't exist.

- **Signal**: `write_attempts > 0` AND `invalid_tool_calls >=
  write_attempts`.
- **Example**: search_replace tasks where the model paraphrases
  `old_str` from memory instead of copying it exactly. Every attempt
  errors; the model retries with a slightly different paraphrase;
  the consecutive-error escape valve eventually fires.
- **Citation**: closest published analog is Aider's edit-format
  evaluation; this is the failure mode that motivated formats like
  unified_diff over single-string replace.

---

## Using this for testing

Two ways to consume the taxonomy:

### Output-only (model-agnostic)

These categories can be detected from just the agent's final
submission + optional auxiliary data:

| category | classifier | required inputs |
|---|---|---|
| `path_fabrication` | `classify_output` | predicted_files, observed_paths (set of paths the agent visited) |
| `superficial_information_matching` | `classify_output` | predicted_files, issue_text |
| `premature_termination` | `classify_output` | turn_count, tool_call_count |
| `format_anchoring` | `classify_output` | raw_response_text |
| `harness_blocked_termination` | `classify_output` | trial outcome + condition flag |
| `harness_blocked_exploration` | `classify_output` | trial outcome + condition flag |
| `hallucinated_tool` | `classify_tool_selection` | ScoreCard.hallucinated_calls |
| `wrong_tool_selected` | `classify_tool_selection` | ScoreCard.selection_matched |
| `missing_required_call` | `classify_tool_selection` | ScoreCard.missing_required |
| `forbidden_tool_called` | `classify_tool_selection` | ScoreCard.forbidden_called |
| `oracle_failed` | `classify_code_editing` | oracle.passed + write_attempts |
| `read_only_loop` | `classify_code_editing` | tool_calls + write_attempts |
| `edit_apply_error` | `classify_code_editing` | invalid_tool_calls vs write_attempts |

If your agent emits these signals (even from a non-OTEL pipeline), you
can call the matching classifier from `agent_eval.failure_modes` and
get a diagnosis. The experiment-specific classifiers take native
experiment data (ScoreCard / oracle) as keyword arguments.

### Trace-required (richer signal)

These need per-turn structured data — the OTEL spans this repo emits
(or an equivalent format):

| category | signals from trace |
|---|---|
| `step_repetition` | per-turn `(tool, args)` signatures + `new_signature` flag |
| `reasoning_action_mismatch` | per-turn `(reasoning_text, action_taken)` pairs |
| `context_amnesia` | full per-turn tool_results + final submission |
| `blind_strategy_switching` | per-turn intent / strategy tags |

For agents that emit OTEL spans with our `agent_eval.tracing`
attributes, `classify_trace(trial_span_id, spans)` returns the full
diagnosis.

---

## References

1. **MAST — Why Do Multi-Agent LLM Systems Fail?** Cemri, Pan et al.,
   NeurIPS 2025 Spotlight. Canonical multi-agent failure taxonomy:
   14 modes in 3 categories. https://arxiv.org/abs/2503.13657
2. **An Empirical Study on Failures in Automated Issue Solving** (2025).
   SWE-bench-style taxonomy: 3 phases (Localization, Repair, Iterative
   Verification), 9 main + 25 sub-categories. Direct ancestor for the
   localization-specific categories above.
   https://arxiv.org/html/2509.13941
3. **AgentBench** (Liu et al., 2023). Classifies failures as Invalid
   Format (IF), Invalid Action (IA), Task Limit Exceeded (TLE).
   https://arxiv.org/abs/2308.03688
4. **MIRAGE-Bench** (Zhang et al., 2025). Benchmark for agent
   hallucination including path/file fabrication.
   https://arxiv.org/pdf/2507.21017
5. **Butterfly Effects in Toolchains** (2025). Five failure categories
   in the tool-agent invocation chain; introduces "parameter name
   hallucination". https://arxiv.org/pdf/2507.15296
6. **Winston & Just, A Taxonomy of Failures in Tool-Augmented LLMs**
   (AST 2025, UW).
   https://homes.cs.washington.edu/~rjust/publ/tallm_testing_ast_2025.pdf
7. **Say One Thing, Do Another? Diagnosing Reasoning-Execution Gaps**
   (2025). Canonical paper distinguishing Reasoning vs. Execution gap.
   https://arxiv.org/pdf/2510.02204
8. **Runaway is Ashamed, But Helpful** (2025). Studies early-exit
   behavior — direct empirical study of premature termination.
   https://arxiv.org/pdf/2505.17616
9. **Surge AI — When Coding Agents Spiral Into 693 Lines of
   Hallucinations** (2025). Practitioner-style report on path
   fabrication cascades in SWE-bench settings.
   https://surgehq.ai/blog/when-coding-agents-spiral-into-693-lines-of-hallucinations
