# code-editing contract

Task / Result / scoring shape every code-editing trial must satisfy.
Source of truth: `src/code_editing/contract.py`.

## Input — `EditTask`

```python
@dataclass
class EditTask:
    task_id:          str
    language:         Literal["python", "typescript"]
    category:         str                   # rename / move / extract_method / ...
    fixture_dir:      Path                  # starter files (copied into the workdir)
    instructions:     str                   # task description shown to the model
    oracle_cmd:       list[str]             # exit 0 == passed
    files_in_context: list[str] = []        # primary files surfaced up front
```

The fixture is a directory of source files; the runner copies them into a
fresh temp workdir, the model edits in place, the runner then merges any
`oracle/` files (typically `_overlay/tests/` hidden from the model) and runs
`oracle_cmd`.

## Output — `EditResult`

```python
@dataclass
class EditResult:
    workdir:           Path     # final state of the edited workdir
    passed:            bool     # oracle_returncode == 0
    oracle_returncode: int
    stdout:            str = ""
    stderr:            str = ""
```

Trials return this internally and convert it to a `RunRecord` for the sweep.
The `extra` dict on the record carries any per-condition metadata (turns,
tool-call counts, fmt-specific stats).

## Scoring — `score(result)`

```python
@dataclass
class EditScore:
    passed:     bool   # binary on oracle exit code
    returncode: int
```

This is the simplest contract of the three experiments: the oracle is the
ground truth. If pytest is green, the trial passed. The richer signal (tokens,
turns, invalid-tool rate, latency) lives on the `RunRecord` itself.

## Adapters — where EditTasks come from

| Adapter | Status | Source |
|---|---|---|
| [`adapters/filesystem.py`](src/code_editing/adapters/filesystem.py) | shipping | local task dirs in `tasks/v2/` (the 42 hand-crafted tasks the experiment owns) |
| [`adapters/aider_polyglot.py`](src/code_editing/adapters/aider_polyglot.py) | shipping | clones [Aider Polyglot](https://github.com/Aider-AI/polyglot-benchmark) and converts each exercise into an EditTask |
| `adapters/hf_swebench.py` | **planned** | SWE-Bench rows → EditTask backed by a real repo checkout at the base commit |
| `adapters/github_pr.py` | **planned** | extract fixture (pre-fix file state) + oracle (tests added by the fix) from a real GitHub PR |

Every adapter returns `EditTask` instances. Trials don't care where the
task came from — they just receive an EditTask, materialize the fixture into
a workdir, run their conditions, and produce a RunRecord.

## Conditions — what trials vary

Currently three execution modes (each is a different way to wire the LLM):

| Condition | What it tests | Module |
|---|---|---|
| `single` | one `tool_use` call (the canonical API path) | `bench/runner.py:run_single_shot` |
| `structured` | one JSON change-set in plain text (no tool_use) | `bench/runner.py:run_structured` |
| `agent` | multi-turn `tool_use` loop with escape valves | `bench/runner.py:run_trial` |

…orthogonal to four format choices (`search_replace`, `unified_diff`,
`semantic`, `search_plus`). The `condition` axis of the sweep is typically
the `format` (or `(mode, format)` cross-tabbed). See
[`notes/tool-use-vs-structured-output.md`](../../notes/tool-use-vs-structured-output.md)
for headline findings.

## How a trial plugs into `agent-eval-core`

The existing `run_single_shot` / `run_structured` / `run_trial` functions
already produce `agent_eval.RunRecord`. To run a sweep:

```python
from agent_eval import Sweep
from code_editing.adapters.filesystem import discover_tasks
from code_editing.formats import FORMAT_REGISTRY
from code_editing.bench.runner import run_structured

tasks = discover_tasks(Path("tasks/v2"))

def trial_factory(format_name: str):
    fmt = FORMAT_REGISTRY[format_name]()
    def trial(client, condition, task):
        # condition is the format name for this experiment
        with tempfile.TemporaryDirectory() as tmp:
            return run_structured(task, client, fmt, Path(tmp))
    return trial

sweep = Sweep(
    models=["claude-sonnet-4-6", "claude-opus-4-7"],
    conditions=["search_plus"],
    tasks=tasks,
    trial=trial_factory("search_plus"),
)
records = sweep.run()
```

In practice the existing CLI (`coding-tool sweep ...`) handles the glue; this
snippet shows the underlying shape.
