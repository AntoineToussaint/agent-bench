# tool-selection contract

Task / Result / scoring shape for tool-selection trials.
Source of truth: `src/tool_selection/types.py` (canonical) + this doc.

This experiment is **not yet refactored** to use `agent-eval-core`. The types
below come from its standalone implementation; once refactored, they'll map
onto the standard `Trial = (ModelClient, condition, task) -> RunRecord`
signature and the contract layout will mirror `code-editing` /
`file-localization`.

## Input — `Task` (`tool_selection.types.Task`)

```python
@dataclass(frozen=True)
class Task:
    task_id:          str
    user_message:     str                       # the instruction in natural language
    required_calls:   tuple[RequiredCall, ...]  # the gold-standard tool succession
    forbidden_tools:  frozenset[str] = ()       # tools that must NOT appear
    notes:            str = ""                  # human commentary, not scored
```

Each `RequiredCall` is a structural constraint:

```python
@dataclass(frozen=True)
class RequiredCall:
    tool:             str                  # the expected tool name
    required_args:    frozenset[str] = ()  # which arg keys must be present
    arg_predicates:   dict[str, Callable] = {}   # optional value-level checks
    order:            int | None = None    # if set, position in the sequence
```

A task encodes both **selection** (which tools to call) and **argumentation**
(with what key arguments).

## Catalogs — `tool_selection.types.Catalog`

A `Catalog` is the toolbox set the model sees during a trial. The
**granularity dimension** controls how many tools represent the same
capability area:

```python
Granularity = Literal[
    "narrow",          # ~40 small tools (one per action)
    "fat",             # ~12 wide tools (action via enum arg)
    "narrow-rich",     # narrow + multi-paragraph descriptions
    "fat-rich",        # fat + multi-paragraph descriptions
    "narrow-rich-80",  # ~80 tools (GitHub-MCP scale)
    "narrow-rich-150", # ~150 tools (multi-MCP setup)
    "primitive",       # ad-hoc primitives, debugging only
]
```

## Output — `CallTrace`

```python
@dataclass
class CallTrace:
    task_id:    str
    approach:   str
    model:      str
    granularity: Granularity
    catalog:    Catalog
    calls:      list[ToolCall]   # the model's response, parsed
    raw:        Any              # provider-native response for replay
    cost_usd:   float
    latency_s:  float
```

## Scoring — `ScoreCard`

`scorer.score(trace, task)` returns:

```python
@dataclass
class ScoreCard:
    selection_correct: bool   # every required tool was called, nothing forbidden
    args_correct:      bool   # required arg keys present + predicates pass
    overall:           bool   # selection AND args
    sel_score:         float  # 0..1 partial credit for selection
    args_score:        float  # 0..1 partial credit for args
    diagnosis:         list[str]   # human-readable failure reasons
```

Selection and args are reported separately because they fail in different ways
and benefit from different mitigations (richer descriptions help args;
catalog filtering helps selection).

## Adapters — where Catalogs and Tasks come from

| Adapter | Status | Source |
|---|---|---|
| `tool_selection.catalogs.*` | shipping | hand-defined Python toolboxes: `filesystem`, `git`, `github` × {narrow, fat, narrow-rich, narrow-rich-80, narrow-rich-150, primitive} |
| `tool_selection.adapters.local_hand_authored` | shipping | 16 hand-authored tasks split by difficulty (easy / medium / hard) and by failure-mode tags (bash / pytest / runner / verify). Underlying lists live in `tool_selection/tasks/`. |
| `adapters/mcp_server.py` | **planned** | live tool inventory from a running MCP server (Anthropic, Modelcontextprotocol.io) |
| `adapters/bfcl.py` | **planned** | [BFCL v3](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard) tasks |
| `adapters/composio.py` | **planned** | [Composio's tool-use eval set](https://composio.dev/) |
| `adapters/trajectbench.py` | **planned** | [TRAJECT-Bench](https://arxiv.org/abs/2509.21796) "confusable sibling" coverage |

Quick recipes:

```python
from tool_selection.adapters import all_tasks, tasks_by_difficulty, tasks_by_failure_mode

all_16 = all_tasks()                       # tuple[Task, ...]
easy_only = tasks_by_difficulty()["easy"]  # tuple[Task, ...]
pytest_only = tasks_by_failure_mode()["pytest"]
```

## Conditions — what trials vary

The experiment's main axes:

| Axis | Values |
|---|---|
| **Surfacing strategy** | `full`, `tool:llm-haiku`, `hybrid:embed-openai-small+llm-haiku` |
| **Phase architecture** | `1phase`, `1phase-plan`, `2phase` |
| **Granularity** | narrow / fat / narrow-rich / narrow-rich-80 / narrow-rich-150 |
| **Final-shot model** | Haiku 4.5 / Sonnet 4.6 / mixed |

The headline finding lives in [`SUMMARY.md`](SUMMARY.md): two-phase
calling scales nearly flat with catalog size while one-phase scales 2.5–4×
worse. See also the cross-experiment writeup at
[`notes/tool-use-vs-structured-output.md`](../../notes/tool-use-vs-structured-output.md).

## Refactor status

- ✅ `tool_selection.contract` re-exports canonical types as the standard import path.
- ✅ `tool_selection.adapters.local_hand_authored` is the local task adapter.
- ✅ `tool_selection.pricing` now delegates to `agent_eval.pricing` (the
  pricing YAML); a small fallback table covers embeddings + research
  placeholders.
- ⏳ `tool_selection.runner` still uses its own sweep loop. Migration to
  `agent_eval.Sweep` is the next step — needs a `trial = (ModelClient,
  approach_str, Task) -> RunRecord` wrapper around the existing
  approach/phase pipeline.
- ⏳ `tool_selection.scorer.ScoreCard` → embed into `RunRecord.extra` once
  the runner moves to `agent_eval.Sweep`.
