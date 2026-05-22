"""Second failure-mode task set: project uses ./tools/run for ops commands.

Same architectural pattern as verify_tasks.py (recurring tool-use mistake that
needs a project-specific convention) but a DIFFERENT surface failure — the
LLM synthesizer has to design a different derived tool.

The naive model attempts (npm run X, make X, bare X, python build.py) all fail.
Only ./tools/run <subcommand> succeeds.
"""

from __future__ import annotations

from tool_selection.matchers import Regex
from tool_selection.types import RequiredCall, Task

from ._failures import bash_tools_run_wrong_path

_CTX = (
    "Repo: tensorzero/playground\n"
    "Operations are run via this project's custom runner. "
    "Available subcommands: build, migrate, seed, deploy, lint, test-all, format.\n"
    "Just run the command — don't investigate the codebase first.\n"
)

R1 = Task(
    id="R1-run-build",
    difficulty="small",
    prompt="Run the build.",
    context=_CTX,
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"\./tools/run\s+build")}),
    ),
    failure_triggers=(bash_tools_run_wrong_path(),),
    note="Naive attempts: 'npm run build', 'make build', 'bash build.sh'. None work.",
)

R2 = Task(
    id="R2-run-migrate",
    difficulty="small",
    prompt="Run the database migrations.",
    context=_CTX,
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"\./tools/run\s+migrate")}),
    ),
    failure_triggers=(bash_tools_run_wrong_path(),),
    note="Same failure mode as R1 — lesson should transfer.",
)

R3 = Task(
    id="R3-run-seed",
    difficulty="small",
    prompt="Seed the development database.",
    context=_CTX,
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"\./tools/run\s+seed")}),
    ),
    failure_triggers=(bash_tools_run_wrong_path(),),
    note="Threshold-crossing failure — should trigger promotion in phase 3.",
)

R4 = Task(
    id="R4-run-lint",
    difficulty="small",
    prompt="Run the linter.",
    context=_CTX,
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"\./tools/run\s+lint")}),
    ),
    failure_triggers=(bash_tools_run_wrong_path(),),
    note="Post-promotion — should use the derived tool first-try.",
)

R5 = Task(
    id="R5-run-deploy",
    difficulty="small",
    prompt="Deploy the app.",
    context=_CTX,
    required_calls=(
        RequiredCall(op="fs.bash", args={"command": Regex(r"\./tools/run\s+deploy")}),
    ),
    failure_triggers=(bash_tools_run_wrong_path(),),
    note="Confirms the derived-tool win holds.",
)

RUNNER_TASKS = (R1, R2, R3, R4, R5)
