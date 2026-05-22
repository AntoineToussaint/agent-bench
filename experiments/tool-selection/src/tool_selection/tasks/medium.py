"""Medium tasks (4-7 required tool calls)."""

from __future__ import annotations

import re

from tool_selection.matchers import Contains, Eq, Present, Regex
from tool_selection.types import RequiredCall, Task

from ._failures import (
    checkout_missing_branch,
    pr_create_before_push,
    push_without_upstream,
    review_event_enum_mismatch,
)

MEDIUM: tuple[Task, ...] = (
    Task(
        id="M1-version-bump-release",
        difficulty="medium",
        prompt=(
            "Cut a 0.4.0 release: bump the version in pyproject.toml from 0.3.0 "
            "to 0.4.0, add a CHANGELOG.md entry under '## 0.4.0 (2026-05-15)' "
            "with the bullets you see in context, stage both files, commit with "
            "message 'release: v0.4.0', and push to origin/main."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: main, up to date with origin.\n\n"
            "Full current contents of pyproject.toml:\n"
            "```\n"
            "[project]\n"
            "name = \"playground\"\n"
            "version = \"0.3.0\"\n"
            "description = \"Internal scratch repo\"\n"
            "requires-python = \">=3.12\"\n"
            "dependencies = [\"anthropic\", \"openai\"]\n"
            "```\n\n"
            "Full current contents of CHANGELOG.md:\n"
            "```\n"
            "# Changelog\n\n"
            "## 0.3.0 (2026-04-22)\n\n"
            "- Initial public release of the scratch repo\n"
            "- Add caching layer for the Anthropic client\n"
            "```\n\n"
            "The new 0.4.0 entry should be inserted ABOVE the 0.3.0 entry, with bullets:\n"
            "  - Add retry-with-backoff to the OpenAI client\n"
            "  - Fix incorrect cost-per-token for Haiku 4.5\n"
            "  - Drop Python 3.11 support\n"
        ),
        required_calls=(
            RequiredCall(
                op="fs.write_overwrite",
                args={"path": Contains("pyproject.toml"), "content": Regex(r'0\.4\.0')},
            ),
            RequiredCall(
                op="fs.write_overwrite",
                args={"path": Contains("CHANGELOG.md"), "content": Contains("0.4.0")},
            ),
            RequiredCall(
                op="git.add",
                args={"paths": Present()},
            ),
            RequiredCall(
                op="git.commit",
                args={"message": Regex(r"release.*0\.4\.0")},
            ),
            RequiredCall(
                op="git.push",
                args={},
            ),
        ),
        strict_order=True,
        note="5-step release flow. Tests that the model writes both files then stages once.",
    ),
    Task(
        id="M2-branch-fix-pr",
        difficulty="medium",
        prompt=(
            "Create a branch 'fix/null-config-handling' off main and switch to it. "
            "Then patch src/config.py so the load_config function raises a clean "
            "FileNotFoundError when the YAML file is missing. Specifically, "
            "add this guard right after the read_yaml call:\n\n"
            "    if config_dict is None:\n"
            "        raise FileNotFoundError(f'Config file not found or empty: {path}')\n\n"
            "Write the full updated file. Stage the change, commit it as "
            "'fix: handle missing config gracefully', push with upstream tracking, "
            "and open a PR titled 'fix: handle missing config gracefully' with "
            "a one-paragraph body explaining the fix."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: main\n\n"
            "Full current contents of src/config.py:\n"
            "```\n"
            "from pathlib import Path\n"
            "from dataclasses import dataclass\n"
            "import yaml\n\n"
            "@dataclass\n"
            "class Config:\n"
            "    env: str\n"
            "    debug: bool = False\n\n"
            "def read_yaml(path: str) -> dict:\n"
            "    return yaml.safe_load(Path(path).read_text())\n\n"
            "def load_config(path: str) -> Config:\n"
            "    config_dict = read_yaml(path)\n"
            "    return Config(env=config_dict['env'], debug=config_dict.get('debug', False))\n"
            "```\n"
        ),
        required_calls=(
            RequiredCall(
                op="git.checkout",
                args={"ref": Eq("fix/null-config-handling")},
                note="Either git_checkout(create=True) shortcut or branch_create + checkout both end here.",
            ),
            RequiredCall(
                op="fs.write_overwrite",
                args={"path": Contains("src/config.py"), "content": Regex(r"if.*config_dict.*is None|if not config_dict|raise FileNotFoundError|config_dict is None")},
            ),
            RequiredCall(op="git.add", args={"paths": Present()}),
            RequiredCall(op="git.commit", args={"message": Contains("handle missing config")}),
            RequiredCall(op="git.push", args={"set_upstream": Eq(True)}),
            RequiredCall(
                op="gh.pr_create",
                args={"title": Contains("handle missing config")},
            ),
        ),
        strict_order=True,
        failure_triggers=(
            checkout_missing_branch("fix/null-config-handling"),
            push_without_upstream("fix/null-config-handling"),
            pr_create_before_push(),
        ),
        note=(
            "7-step flow. The git.checkout(create=True) shortcut is the cleanest; "
            "a separate branch_create + checkout is acceptable but adds a step. "
            "We score the checkout-create form only; if the model splits it, "
            "it'll show up as extra_calls (acceptable noise). "
            "Multi-turn: three deterministic failures encode realistic git mistakes "
            "(missing-branch checkout, new-branch push without upstream, PR before push)."
        ),
    ),
    Task(
        id="M3-inline-review-comment",
        difficulty="medium",
        prompt=(
            "I just reviewed PR #321. Two things:\n"
            "1. On src/parser.py, line 45 (the new function), leave an INLINE "
            "review comment: 'This needs to handle the case where `tokens` is "
            "empty — currently it raises IndexError.'\n"
            "2. Submit my overall review with REQUEST_CHANGES, body: 'A few "
            "issues with edge cases — see inline. Otherwise looks great.'"
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "PR #321 is open. The diff includes a new function in src/parser.py "
            "around line 45 that does `return tokens[0]` without a length check."
        ),
        required_calls=(
            RequiredCall(
                op="gh.pr_review_comment",
                args={
                    "number": Eq(321),
                    "path": Contains("src/parser.py"),
                    "line": Eq(45),
                    "body": Contains("empty"),
                },
            ),
            RequiredCall(
                op="gh.pr_review_submit",
                args={
                    "number": Eq(321),
                    "event": Eq("REQUEST_CHANGES"),
                    "body": Contains("inline"),
                },
            ),
        ),
        strict_order=True,
        forbidden_ops=("gh.pr_comment",),
        failure_triggers=(
            review_event_enum_mismatch(),
        ),
        note=(
            "Strong confusable test. The model must distinguish inline review "
            "comments from conversation comments AND from the review-submit "
            "verdict. Using gh.pr_comment here is a forbidden mistake. "
            "Multi-turn: trigger fires on event='APPROVED' (vs correct 'APPROVE')."
        ),
    ),
    Task(
        id="M5-argument-coupling",
        difficulty="medium",
        prompt=(
            "Bump the default timeout in src/api_client.py: the constant "
            "`TIMEOUT_S` (currently `5`) needs to become `30`. It's defined on "
            "line 14. Write the full updated file, then commit it with a "
            "message of the exact form: "
            "'fix: TIMEOUT_S L<LINE> <OLD>s -> <NEW>s' "
            "where <LINE>, <OLD>, <NEW> are the actual values from this task."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: fix/timeout\n\n"
            "Full current contents of src/api_client.py:\n"
            "```\n"
            "from __future__ import annotations\n\n"
            "import httpx\n\n"
            "BASE_URL = 'https://api.tensorzero.com'\n"
            "API_KEY_HEADER = 'X-Api-Key'\n\n"
            "# Default per-request timeout in seconds. Override per-call via\n"
            "# the `timeout=` kwarg on send().\n"
            "TIMEOUT_S = 5\n\n"
            "class Client:\n"
            "    def __init__(self, key: str):\n"
            "        self._client = httpx.Client(timeout=TIMEOUT_S)\n"
            "```\n\n"
            "(TIMEOUT_S = 5 is on line 14 of the file shown above.)\n"
        ),
        required_calls=(
            RequiredCall(
                op="fs.write_overwrite",
                args={
                    "path": Contains("api_client.py"),
                    "content": Regex(r"TIMEOUT_S\s*=\s*30"),
                },
            ),
            RequiredCall(op="git.add", args={"paths": Contains("api_client.py")}),
            RequiredCall(
                op="git.commit",
                args={
                    "message": Regex(r"fix:\s*TIMEOUT_S\s+L\s*14\s+5s?\s*->\s*30s?", re.IGNORECASE)
                },
            ),
        ),
        strict_order=True,
        note=(
            "Argument-coupling test (Composio 2026 'primary bottleneck'): the "
            "commit message MUST embed the line number (14), old value (5), and "
            "new value (30) — all of which the model has to lift from the task/"
            "context, not from any tool result. Tests whether the model can "
            "thread state from one logical step (the edit) into args of a "
            "subsequent step (the commit)."
        ),
    ),
    Task(
        id="M6-wrong-order-temptation",
        difficulty="medium",
        prompt=(
            "I have edits in src/ratelimit.py that I want to ship. Please push "
            "my branch to origin and then commit my staged changes with the "
            "message 'fix: tune rate limit thresholds'. The file is already "
            "modified — you just need to stage, commit, and push."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: fix/ratelimit (already pushed previously)\n"
            "`git status`:\n"
            "  modified:   src/ratelimit.py\n"
        ),
        required_calls=(
            RequiredCall(op="git.add", args={"paths": Contains("ratelimit.py")}),
            RequiredCall(op="git.commit", args={"message": Contains("rate limit")}),
            RequiredCall(op="git.push", args={}),
        ),
        strict_order=True,
        note=(
            "Wrong-order temptation (KAMI / BFCL order errors): the user's "
            "natural-language order is push-then-commit, which is wrong. The "
            "correct execution order is add -> commit -> push. With "
            "strict_order=True, the scorer accepts only that order."
        ),
    ),
    Task(
        id="M7-state-confusion-mkdir",
        difficulty="medium",
        prompt=(
            "Move src/helpers.py into src/utils/ (so it becomes "
            "src/utils/helpers.py). Then stage the rename and commit it as "
            "'refactor: move helpers into utils/'."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: refactor/structure\n"
            "Directory listing of src/:\n"
            "  src/\n"
            "  ├── helpers.py        (file to move)\n"
            "  ├── utils/            (directory already exists)\n"
            "  └── utils/__init__.py (already present, do not modify)\n"
        ),
        required_calls=(
            RequiredCall(
                op="fs.move",
                args={
                    "source": Contains("helpers.py"),
                    "destination": Contains("utils/helpers.py"),
                },
            ),
            RequiredCall(op="git.add", args={"paths": Present()}),
            RequiredCall(
                op="git.commit",
                args={"message": Contains("helpers")},
            ),
        ),
        strict_order=True,
        forbidden_ops=("fs.mkdir",),
        note=(
            "State-confusion test (BFCL v3 'mkdir alex while in alex/'): the "
            "destination directory src/utils/ already exists per the context. "
            "A model that calls fs.mkdir 'just to be safe' fails on the "
            "forbidden_ops check. Tests whether the model trusts pre-surfaced "
            "state instead of being over-cautious."
        ),
    ),
    Task(
        id="M8-parallel-similar-batched-commit",
        difficulty="medium",
        prompt=(
            "Three client files all hard-code the same wrong base URL "
            "(`localhost:8000`). Update each to use `api.tensorzero.com` "
            "instead. After all three edits are done, stage all three together "
            "and commit them as ONE commit with message: "
            "'fix: point clients to prod URL'."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: fix/client-url\n\n"
            "All three files have IDENTICAL current contents:\n"
            "```\n"
            "BASE_URL = 'localhost:8000'\n"
            "```\n\n"
            "Files to update (full paths):\n"
            "  - src/client_a.py\n"
            "  - src/client_b.py\n"
            "  - src/client_c.py\n\n"
            "Each file becomes:\n"
            "```\n"
            "BASE_URL = 'api.tensorzero.com'\n"
            "```\n"
        ),
        required_calls=(
            RequiredCall(
                op="fs.write_overwrite",
                args={"path": Contains("client_a.py"), "content": Contains("api.tensorzero.com")},
            ),
            RequiredCall(
                op="fs.write_overwrite",
                args={"path": Contains("client_b.py"), "content": Contains("api.tensorzero.com")},
            ),
            RequiredCall(
                op="fs.write_overwrite",
                args={"path": Contains("client_c.py"), "content": Contains("api.tensorzero.com")},
            ),
            RequiredCall(
                op="git.add",
                args={"paths": Contains("client_a.py")},
                note="The git.add call must include all three files; we check one specifically here for matching. The scorer's strict-order pass will consume this entry on whichever git_add call matches first.",
            ),
            RequiredCall(
                op="git.commit",
                args={"message": Contains("prod URL")},
            ),
        ),
        strict_order=False,
        note=(
            "Parallel-similar-batched test: 3 near-identical fs.write calls "
            "(testing that the model doesn't get confused by similarity), "
            "followed by ONE git.add covering all three (NOT three separate "
            "adds), followed by ONE commit. A model that does 3 separate "
            "add+commit cycles will pass via extra_calls noise but the "
            "intended pattern is batched."
        ),
    ),
    Task(
        id="M4-rename-and-commit",
        difficulty="medium",
        prompt=(
            "Rename src/old_helpers.py to src/helpers.py (just the file move; "
            "the contents are fine). Stage the rename and commit it as "
            "'refactor: rename old_helpers.py → helpers.py'."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "src/old_helpers.py exists; src/helpers.py does not.\n"
            "Current branch: refactor/cleanup\n"
        ),
        required_calls=(
            RequiredCall(
                op="fs.move",
                args={
                    "source": Contains("old_helpers.py"),
                    "destination": Contains("helpers.py"),
                },
            ),
            RequiredCall(op="git.add", args={"paths": Present()}),
            RequiredCall(
                op="git.commit",
                args={"message": Regex(r"rename.*helpers")},
            ),
        ),
        strict_order=True,
        note="Tests fs.move (vs delete + create). 3 steps.",
    ),
)
