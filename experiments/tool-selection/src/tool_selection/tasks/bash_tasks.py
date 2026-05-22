"""Bash-based pytest tasks — the real engineering failure mode.

Same four tasks as pytest_tasks.py but routed through the unstructured `bash`
tool instead of the structured `run_tests` tool. The model has to COMPOSE the
shell invocation; there's no schema to enforce the path rule.

The `bash` tool's description even includes the bad example (`pytest test_auth.py`
without tests/ prefix) — mirroring real MCP/docs where suboptimal examples
recur in training data. A model that copies the example pattern will fail.

Required call: a bash invocation containing `pytest tests/<file>` (the correct
form). The failure trigger fires on `pytest <bare-filename>` (wrong form).
"""

from __future__ import annotations

from tool_selection.matchers import Contains, Regex
from tool_selection.types import RequiredCall, Task

from ._failures import bash_pytest_wrong_path

BT1 = Task(
    id="BT1-bash-run-auth-tests",
    difficulty="small",
    prompt=(
        "Run the auth tests to verify nothing broke. Use bash."
    ),
    context=(
        "Repo: tensorzero/playground\n"
        "Project layout:\n"
        "  src/auth.py\n"
        "  tests/test_auth.py\n"
        "  pyproject.toml (with [tool.pytest.ini_options])\n"
    ),
    required_calls=(
        RequiredCall(
            op="fs.bash",
            args={"command": Regex(r"pytest\s+tests/test_auth\.py")},
        ),
    ),
    failure_triggers=(bash_pytest_wrong_path(),),
    note=(
        "Bash primitive. Model has to compose 'pytest tests/test_auth.py'. "
        "Bare 'pytest test_auth.py' (which is what the description's example "
        "literally shows) fails. Same failure mode as BT2-BT4 for lesson transfer."
    ),
)

BT2 = Task(
    id="BT2-bash-run-parser-tests",
    difficulty="small",
    prompt=(
        "Verify the parser module still passes its tests. Use bash."
    ),
    context=(
        "Repo: tensorzero/playground\n"
        "Project layout:\n"
        "  src/parser.py\n"
        "  tests/test_parser.py\n"
    ),
    required_calls=(
        RequiredCall(
            op="fs.bash",
            args={"command": Regex(r"pytest\s+tests/test_parser\.py")},
        ),
    ),
    failure_triggers=(bash_pytest_wrong_path(),),
    note="Same failure mode as BT1 — lesson should transfer.",
)

BT3 = Task(
    id="BT3-bash-run-integration",
    difficulty="small",
    prompt=(
        "Run the integration tests to verify the client refactor. Use bash."
    ),
    context=(
        "Repo: tensorzero/playground\n"
        "Project layout:\n"
        "  src/client_a.py, client_b.py\n"
        "  tests/integration/test_clients.py\n"
        "  tests/integration/test_flow.py\n"
    ),
    required_calls=(
        RequiredCall(
            op="fs.bash",
            args={"command": Regex(r"pytest\s+tests/integration")},
        ),
    ),
    failure_triggers=(bash_pytest_wrong_path(),),
    note="Subdirectory variant. Bare 'integration/' fails; 'tests/integration/' succeeds.",
)

BT4 = Task(
    id="BT4-bash-run-single",
    difficulty="small",
    prompt=(
        "Run just the test_login function from the auth tests — I'm iterating on it. Use bash."
    ),
    context=(
        "Repo: tensorzero/playground\n"
        "Project layout:\n"
        "  tests/test_auth.py:\n"
        "    def test_login(): ...\n"
        "    def test_logout(): ...\n"
        "pytest node-id syntax: 'tests/test_auth.py::test_login'\n"
    ),
    required_calls=(
        RequiredCall(
            op="fs.bash",
            args={"command": Regex(r"pytest\s+tests/test_auth\.py::test_login")},
        ),
    ),
    failure_triggers=(bash_pytest_wrong_path(),),
    note="Same failure family; tests pytest node-id composition.",
)

BASH_TASKS = (BT1, BT2, BT3, BT4)
