"""Tasks centered on running tests — the canonical real-world engineering
failure the user has seen repeatedly. The model is asked to run tests; the
'natural' first attempt uses a bare filename and gets 'collected 0 items';
the lesson is to prefix paths with 'tests/'.

All four tasks share the same failure mode → maximum lesson transfer signal.
"""

from __future__ import annotations

from tool_selection.matchers import Contains, Eq, Present, Regex
from tool_selection.types import RequiredCall, Task

from ._failures import bash_pytest_wrong_path, wrong_test_path

# ---------- T1: Run the auth tests ----------

T1_RUN_AUTH_TESTS = Task(
    id="T1-run-auth-tests",
    difficulty="small",
    prompt=(
        "I just edited src/auth.py — please run the auth tests to confirm nothing broke."
    ),
    context=(
        "Repo: tensorzero/playground\n"
        "Project layout:\n"
        "  src/auth.py\n"
        "  tests/test_auth.py\n"
        "  tests/integration/test_login_flow.py\n"
        "  pyproject.toml (has [tool.pytest.ini_options] testpaths = ['tests'])\n"
    ),
    required_calls=(
        RequiredCall(
            op="fs.run_tests",
            args={"test_path": Regex(r"tests/test_auth\.py")},
        ),
    ),
    failure_triggers=(wrong_test_path(),),
    note=(
        "First-attempt failure mode: agent calls run_tests(test_path='test_auth.py') — the bare "
        "filename — which pytest reports as 'collected 0 items'. The lesson is to prefix with "
        "'tests/'. Identical failure mode appears in T2/T3/T4 → strong lesson-transfer signal."
    ),
)


# ---------- T2: Run the parser tests ----------

T2_RUN_PARSER_TESTS = Task(
    id="T2-run-parser-tests",
    difficulty="small",
    prompt=(
        "Verify the parser module still passes its test suite. I just refactored "
        "src/parser.py and want to make sure I didn't break anything."
    ),
    context=(
        "Repo: tensorzero/playground\n"
        "Project layout:\n"
        "  src/parser.py\n"
        "  tests/test_parser.py     (the main parser tests)\n"
        "  tests/test_parser_edge_cases.py\n"
    ),
    required_calls=(
        RequiredCall(
            op="fs.run_tests",
            args={"test_path": Regex(r"tests/test_parser")},
        ),
    ),
    failure_triggers=(wrong_test_path(),),
    note=(
        "Same failure mode as T1. If T1 generated a lesson about prefixing with 'tests/', "
        "the agent should succeed first try on T2."
    ),
)


# ---------- T3: Run the integration tests ----------

T3_RUN_INTEGRATION_TESTS = Task(
    id="T3-run-integration-tests",
    difficulty="small",
    prompt=(
        "Run the integration suite — I want to see if the recent client_a/b/c URL update "
        "broke anything end-to-end."
    ),
    context=(
        "Repo: tensorzero/playground\n"
        "Project layout:\n"
        "  src/client_a.py, client_b.py, client_c.py\n"
        "  tests/test_clients.py             (unit)\n"
        "  tests/integration/test_clients.py (integration — what we want)\n"
        "  tests/integration/test_flow.py\n"
    ),
    required_calls=(
        RequiredCall(
            op="fs.run_tests",
            args={"test_path": Regex(r"tests/integration")},
        ),
    ),
    failure_triggers=(wrong_test_path(),),
    note=(
        "Same failure mode + tests a subdirectory invocation (not just a file). "
        "Bare 'integration/' or 'integration' fails; 'tests/integration/' succeeds."
    ),
)


# ---------- T4: Run a single test method ----------

T4_RUN_SINGLE_TEST = Task(
    id="T4-run-single-test",
    difficulty="small",
    prompt=(
        "Run just the test_login function from the auth tests — I'm iterating on that one "
        "and don't want to wait for the full suite."
    ),
    context=(
        "Repo: tensorzero/playground\n"
        "Project layout:\n"
        "  src/auth.py\n"
        "  tests/test_auth.py:\n"
        "    def test_login(): ...\n"
        "    def test_logout(): ...\n"
        "    def test_refresh(): ...\n"
        "pytest 'node-id' syntax for one test: 'tests/test_auth.py::test_login'\n"
    ),
    required_calls=(
        RequiredCall(
            op="fs.run_tests",
            args={"test_path": Regex(r"tests/test_auth\.py::test_login")},
        ),
    ),
    failure_triggers=(wrong_test_path(),),
    note=(
        "Same failure mode + tests pytest node-id syntax. Bare 'test_auth.py::test_login' "
        "fails; 'tests/test_auth.py::test_login' succeeds."
    ),
)


PYTEST_TASKS = (T1_RUN_AUTH_TESTS, T2_RUN_PARSER_TESTS, T3_RUN_INTEGRATION_TESTS, T4_RUN_SINGLE_TEST)
