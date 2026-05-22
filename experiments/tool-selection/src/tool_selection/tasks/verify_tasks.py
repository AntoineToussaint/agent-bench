"""Phase-3 task set: project uses a NON-STANDARD test directory (`verify/`
instead of `tests/`). No model knows this from pretraining.

Combined with the primitive catalog (only bash; no structured run_tests),
and a sparse bash description (no examples, no convention hints), this
setup defeats all three redundancy layers identified in phase 2:
  - Layer 1 (catalog design): no structured alternative
  - Layer 2 (description quality): bash desc says nothing useful
  - Layer 3 (model pretraining): the verify/ convention isn't standard

The model's first attempt will use bash(pytest test_X.py) or
bash(pytest tests/test_X.py) — both fail. Only bash(pytest verify/test_X.py)
succeeds.

Lesson-learning hypothesis: after V1 fails, the lesson 'tests live in verify/'
should let V2-V5 succeed first try. If we then promote the lesson to a
derived `pytest_verify(test)` tool after N occurrences, V4/V5 should use
the derived tool directly.
"""

from __future__ import annotations

from tool_selection.matchers import Contains, Regex
from tool_selection.types import RequiredCall, Task

from ._failures import bash_pytest_wrong_verify_dir

_CTX_TEMPLATE = (
    "Repo: tensorzero/playground\n"
    "Module under test: src/{module}.py\n"
    "Test framework: pytest (configured in pyproject.toml)\n"
    "Just run the tests — do not investigate the codebase first.\n"
)

V1 = Task(
    id="V1-verify-auth",
    difficulty="small",
    prompt="Please run the auth tests to verify nothing broke.",
    context=_CTX_TEMPLATE.format(module="auth"),
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"pytest\s+verify/(\S*auth\S*|\s*$|\s)")}),
    ),
    failure_triggers=(bash_pytest_wrong_verify_dir(),),
    note="Naive attempt: 'pytest test_auth.py' or 'pytest tests/test_auth.py'. Both fail. Lesson: verify/ is the test dir.",
)

V2 = Task(
    id="V2-verify-parser",
    difficulty="small",
    prompt="Verify the parser tests still pass.",
    context=_CTX_TEMPLATE.format(module="parser"),
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"pytest\s+verify/(\S*parser\S*|\s*$|\s)")}),
    ),
    failure_triggers=(bash_pytest_wrong_verify_dir(),),
    note="Same failure mode as V1. With a lesson from V1, should pass first try.",
)

V3 = Task(
    id="V3-verify-client",
    difficulty="small",
    prompt="Run the client module tests.",
    context=_CTX_TEMPLATE.format(module="client"),
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"pytest\s+verify/(\S*client\S*|\s*$|\s|-k\s+client)")}),
    ),
    failure_triggers=(bash_pytest_wrong_verify_dir(),),
    note="Third recurrence — should trigger lesson → derived tool promotion in phase 3.",
)

V4 = Task(
    id="V4-verify-config",
    difficulty="small",
    prompt="Run the config tests please.",
    context=_CTX_TEMPLATE.format(module="config"),
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"pytest\s+verify/(\S*config\S*|\s*$|\s|-k\s+config)")}),
    ),
    failure_triggers=(bash_pytest_wrong_verify_dir(),),
    note=(
        "Fourth episode — if the derived tool was promoted after V3, this should use the "
        "derived tool directly (which encodes the verify/ convention structurally)."
    ),
)

V5 = Task(
    id="V5-verify-db",
    difficulty="small",
    prompt="Run the db tests.",
    context=_CTX_TEMPLATE.format(module="db"),
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"pytest\s+verify/(\S*db\S*|\s*$|\s|-k\s+db)")}),
    ),
    failure_triggers=(bash_pytest_wrong_verify_dir(),),
    note="Fifth episode — confirms the derived-tool promotion holds.",
)

VERIFY_TASKS = (V1, V2, V3, V4, V5)
