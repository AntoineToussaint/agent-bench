# Authoring guide for v2 benchmark tasks

This is the shared spec for everyone authoring tasks under `tasks/v2/`. The
canonical worked example is `tasks/v2/c03_xfile_rename/` — read it carefully
before authoring anything new.

## Per-task layout

```
tasks/v2/<category_dir>/<size>/
  task.yaml
  fixture/                    # copied VERBATIM into the workdir
    ...
  oracle/
    _overlay/
      tests/
        test_<something>.py   # the oracle tests
  canonical_solution.py
```

Sizes are `small` | `medium` | `large`. Every category has one task per size.

## Shared base codebases (DO NOT MODIFY)

- `tasks/v2/_base/medium/` — mini e-commerce, ~400 LoC, 6 modules in `ecom/` + 2 test files + `conftest.py`.
- `tasks/v2/_base/large/` — same plus `auth.py`, `coupons.py`, `reports.py`, `inventory.py` + 4 more test files. ~900 LoC.

For **medium** and **large** tasks: copy the corresponding base codebase into
`fixture/`. If your task needs a different starting state (e.g. a "fix the
bug" task must INTRODUCE the bug), modify the copy after cloning.

For **small** tasks: write a self-contained fixture (~50 LoC, 1–3 files).
Do NOT reuse the base codebases for small.

## Required files

### `task.yaml`
```yaml
task_id: <category_dir>__<size>     # e.g. c04_signature_change__medium
language: python
category: <short_category_name>     # e.g. signature_change
instructions: |
  <what the model must do, as if a senior engineer wrote a ticket>
  <be specific about which files / which symbols / what behaviour>
files_in_context:                   # 1–3 primary files to embed in the user prompt
  - ecom/<file>.py                  # let view_file/list_files discover the rest
oracle_cmd: ["python", "-m", "pytest", "-q", "tests/", "_overlay/tests/"]
```

### `oracle/_overlay/tests/test_*.py`
The `_overlay/` prefix is critical — the harness *hides files under `_overlay/`
from the model* (filtered in `list_files`; `view_file` errors on them).
Without it the model could read the oracle and game the benchmark.

Standard preamble:
```python
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # workdir root
sys.path.insert(0, str(ROOT))
```

When asserting old names are gone, **use word-boundary regex**, not substring
`in` checks — test function names often contain renamed identifiers as
substrings:
```python
OLD = re.compile(r"\bold_name\b")
assert not OLD.search((ROOT / "ecom/foo.py").read_text())
```

### `canonical_solution.py`
Exposes a single function:
```python
from pathlib import Path

def apply(workdir: Path) -> None:
    """Apply the canonical (correct) edit to the materialized workdir."""
```

Must skip `_overlay/` and `__pycache__/`:
```python
for p in workdir.rglob("*.py"):
    if "__pycache__" in p.parts or "_overlay" in p.parts:
        continue
```

## Validation

After authoring, every task you wrote MUST pass:
```bash
cd /Users/antoine/Development/research/coding-tool
uv run pytest tests/test_v2_oracles.py -v
```

That test (a) materializes each task's fixture, (b) runs your canonical
solution against it, (c) executes the oracle, (d) asserts pass. If your
canonical+oracle pair doesn't pass this test, the task is broken — fix
before declaring done.

## Style

- `from __future__ import annotations` at the top of fixture .py files
- match the base codebases' style: brief module docstrings, dataclasses,
  no decorator soup, no docstring on every function
- no emojis, no breezy comments
- realistic code — the fixture should feel like a small production module,
  not a toy
- oracle tests are concise; 4–7 assertions per task is right
