# file-localization contract

The Task / Result / scoring shape every localization trial in this experiment
must satisfy. Source of truth: `src/file_localization/contract.py`.

## Input — `LocalizationTask`

```python
@dataclass(frozen=True)
class LocalizationTask:
    instance_id:       str                       # e.g. "django__django-12345"
    issue_text:        str                       # the GitHub issue
    repo:              str                       # "django/django"
    base_commit:       str                       # SHA at the time of the issue
    gold_edit_files:   frozenset[str]            # what the gold patch modifies
    gold_test_files:   frozenset[str]            # what the gold test patch modifies
    repo_file_list:    tuple[str, ...] | None    # optional candidate set
```

A SWE-Bench row maps cleanly via `swebench_adapter.to_localization_task` —
the gold sets are parsed out of the unified-diff patches.

## Output — `LocalizationResult`

```python
@dataclass
class LocalizationResult:
    predicted_files: list[str]   # ranked, most-confident first
    reasoning:       str = ""    # optional, ignored by the scorer
```

Trials don't return `LocalizationResult` directly to the sweep — they produce
an `agent_eval.RunRecord` whose `extra` dict carries the parsed prediction +
scoring metrics. The `LocalizationResult` type is the internal contract a
trial produces *before* converting.

## Scoring — `contract.score(predicted, gold, *, k=None, fp_penalty=0.05)`

Returns a `LocalizationScore` with six numbers:

| metric | definition | when to use |
|---|---|---|
| `recall` | `\|predicted ∩ gold\| / \|gold\|` | did we find the gold files? |
| `precision` | `\|predicted ∩ gold\| / \|predicted\|` | were our guesses on-target? |
| `f1` | harmonic mean | single-number summary |
| `passed` | `recall == 1.0` | strict pass/fail for the sweep report |
| `n_false_positives` | `\|predicted\| − \|predicted ∩ gold\|` | how much spam? |
| `composite` | `recall − fp_penalty · (fp / max(1, \|gold\|))` | penalize spam |

The composite is the recommended single-number ranking: it equals `recall` for
a perfect, no-spam answer and decays by `fp_penalty` for each spurious file
(normalized by gold-set size so big and small tasks compare).

## How a trial plugs into `agent-eval-core`

```python
from agent_eval import Sweep, RunRecord
from file_localization.data import load_tasks
from file_localization.swebench_adapter import to_localization_tasks
from file_localization.llm_trial import make_llm_trial

raw = load_tasks("verified", split="test")[:50]   # smoke subset
tasks = to_localization_tasks(raw)

sweep = Sweep(
    models=["claude-haiku-4-5", "claude-sonnet-4-6"],
    conditions=["bare-issue", "issue-plus-filelist"],  # whatever you vary
    tasks=tasks,
    trial=make_llm_trial(top_k=10),
)
records = sweep.run()
```

Each record's `extra` dict carries `recall`, `precision`, `f1`,
`n_predicted`, `n_false_positives`, `composite` — slice and aggregate however
you want for the report.

## Why the contract matters

- **Multiple retrievers, same scoring.** The existing BM25 / ripgrep /
  semble retrievers can be wrapped as Trial functions that produce the same
  `RunRecord` shape. Then the sweep compares them apples-to-apples with LLM
  retrievers, on the same tasks, using the same metrics.
- **No measurement coupling.** Adding a new retriever doesn't touch the
  scoring code, the dataset loader, or the sweep runner. Just implement
  `(client, condition, task) -> RunRecord`.
- **Direct compatibility with the library.** `LocalizationTask.task_id`
  matches `RunRecord.task_id`, so `agent_eval.reports.write_markdown` Just
  Works on the results.
