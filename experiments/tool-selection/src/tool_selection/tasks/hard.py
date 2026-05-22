"""Hard tasks (8+ required tool calls)."""

from __future__ import annotations

from tool_selection.matchers import Contains, Eq, Present, Regex
from tool_selection.types import RequiredCall, Task

from ._failures import (
    pr_create_before_push,
    push_without_upstream,
    review_event_enum_mismatch,
)

HARD: tuple[Task, ...] = (
    Task(
        id="H3-hotfix-with-cross-step-coupling",
        difficulty="large",
        prompt=(
            "Hotfix workflow for a production race condition reported in "
            "issue #87. Do all of the following in one shot:\n"
            "1. Switch to main and pull from origin.\n"
            "2. Create branch 'hotfix/db-cursor-race' off the just-pulled main "
            "and switch to it.\n"
            "3. Rewrite src/db.py with the patched contents in the context block "
            "(adds `with self._lock:` around the cursor.execute call).\n"
            "4. Stage the change and commit it as 'hotfix: serialize DB cursor "
            "access (fixes #87)' — the issue number must appear in the message.\n"
            "5. Push to origin with upstream tracking.\n"
            "6. Open a NON-DRAFT PR titled 'Hotfix: DB cursor race condition' "
            "with a body that explicitly mentions both the issue (#87) and the "
            "file changed (src/db.py)."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: main (origin slightly ahead — you must pull)\n"
            "Issue #87: 'DB connection pool: cursor.execute() interleaves under "
            "concurrent load'. Filed by oncall last Friday.\n\n"
            "Full patched contents for src/db.py:\n"
            "```\n"
            "from __future__ import annotations\n\n"
            "import threading\n"
            "import psycopg2\n\n"
            "class DB:\n"
            "    def __init__(self, dsn: str):\n"
            "        self._conn = psycopg2.connect(dsn)\n"
            "        self._lock = threading.Lock()\n\n"
            "    def execute(self, sql: str, params: tuple = ()) -> list:\n"
            "        with self._lock:\n"
            "            cursor = self._conn.cursor()\n"
            "            cursor.execute(sql, params)\n"
            "            return cursor.fetchall()\n"
            "```\n"
        ),
        required_calls=(
            RequiredCall(op="git.checkout", args={"ref": Eq("main")}),
            RequiredCall(op="git.pull", args={}),
            RequiredCall(
                op="git.checkout",
                args={"ref": Eq("hotfix/db-cursor-race")},
                note="Either branch_create+checkout(ref) or checkout(ref, create=True) is fine.",
            ),
            RequiredCall(
                op="fs.write_overwrite",
                args={"path": Contains("src/db.py"), "content": Contains("with self._lock")},
            ),
            RequiredCall(op="git.add", args={"paths": Contains("db.py")}),
            RequiredCall(
                op="git.commit",
                args={"message": Regex(r"hotfix.*#87")},
            ),
            RequiredCall(op="git.push", args={"set_upstream": Eq(True)}),
            RequiredCall(
                op="gh.pr_create",
                args={
                    "title": Contains("DB cursor"),
                    # [\s\S] used in place of `.` because real PR bodies span
                    # multiple lines and Python's `.` does not match newlines
                    # by default.
                    "body": Regex(r"#87[\s\S]*src/db\.py|src/db\.py[\s\S]*#87"),
                    "draft": Eq(False),
                },
                note="Body must reference BOTH the issue number AND the file — argument-coupling stress.",
            ),
        ),
        strict_order=True,
        failure_triggers=(
            push_without_upstream("hotfix/db-cursor-race"),
            pr_create_before_push(),
        ),
        note=(
            "Hotfix workflow with cross-step coupling: 8 calls, multiple "
            "argument-coupling pressure points — the commit message must "
            "embed '#87', the PR title must mention 'DB cursor', the PR body "
            "must reference both #87 and src/db.py. Tests whether the model "
            "carries state across many tool calls in one shot. "
            "Multi-turn: same push-without-upstream + PR-before-push failures "
            "as M2 → tests lesson transfer across task boundaries."
        ),
    ),
    Task(
        id="H1-feature-branch-full-flow",
        difficulty="large",
        prompt=(
            "Build out a dark-mode feature, step by step:\n"
            "1. Create branch 'feature/dark-mode' off main and switch to it.\n"
            "2. Create src/themes/dark.css with the CSS in the context block.\n"
            "3. Append an @import line to src/themes/index.css so the new file is "
            "loaded.\n"
            "4. Create tests/test_dark_mode.py with the test stub in the context "
            "block.\n"
            "5. Stage and commit the CSS file with message 'feat(themes): add dark "
            "mode stylesheet'.\n"
            "6. Stage and commit the index.css update with message 'feat(themes): "
            "wire dark mode into theme loader'.\n"
            "7. Stage and commit the test with message 'test(themes): add dark "
            "mode test stub'.\n"
            "8. Push with upstream tracking.\n"
            "9. Open a non-draft PR titled 'Add dark mode theme' with body "
            "summarizing the three commits."
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "Current branch: main\n"
            "tests/ and src/themes/ both exist.\n\n"
            "Content for src/themes/dark.css:\n"
            "  :root[data-theme='dark'] {\n"
            "    --bg: #0d1117;\n"
            "    --fg: #e6edf3;\n"
            "    --accent: #58a6ff;\n"
            "  }\n\n"
            "Line to append to src/themes/index.css:\n"
            "  @import './dark.css';\n\n"
            "Stub for tests/test_dark_mode.py:\n"
            "  def test_dark_mode_loads():\n"
            "      assert True  # TODO: wire up theme loader\n"
        ),
        required_calls=(
            RequiredCall(
                op="git.checkout",
                args={"ref": Eq("feature/dark-mode")},
                note="Either of the two natural paths ends with this checkout: (a) git_branch_create + git_checkout(ref), or (b) git_checkout(ref, create=True). We only require the checkout itself.",
            ),
            RequiredCall(
                op="fs.write_create",
                args={"path": Contains("dark.css"), "content": Contains("--bg")},
            ),
            RequiredCall(
                op="fs.write_append",
                args={"path": Contains("index.css"), "content": Contains("@import")},
            ),
            RequiredCall(
                op="fs.write_create",
                args={"path": Contains("test_dark_mode.py"), "content": Contains("def test_dark_mode_loads")},
            ),
            RequiredCall(
                op="git.add",
                args={"paths": Contains("dark.css")},
                note="First commit stages dark.css.",
            ),
            RequiredCall(
                op="git.commit",
                args={"message": Regex(r"feat\(themes\).*dark.*stylesheet")},
            ),
            RequiredCall(
                op="git.add",
                args={"paths": Contains("index.css")},
                note="Second commit stages index.css.",
            ),
            RequiredCall(
                op="git.commit",
                args={"message": Regex(r"feat\(themes\).*wire.*loader")},
            ),
            RequiredCall(
                op="git.add",
                args={"paths": Contains("test_dark_mode.py")},
            ),
            RequiredCall(
                op="git.commit",
                args={"message": Regex(r"test\(themes\)")},
            ),
            RequiredCall(op="git.push", args={"set_upstream": Eq(True)}),
            RequiredCall(
                op="gh.pr_create",
                args={"title": Contains("dark mode")},
            ),
        ),
        strict_order=True,
        failure_triggers=(
            push_without_upstream("feature/dark-mode"),
            pr_create_before_push(),
        ),
        note=(
            "12-step end-to-end feature flow. Tests fs.write_create vs "
            "fs.write_append distinction, plus three discrete commits "
            "(verifying the model doesn't squash into one). "
            "Multi-turn: push-without-upstream + PR-before-push failures."
        ),
    ),
    Task(
        id="H2-pr-multi-inline-review",
        difficulty="large",
        prompt=(
            "Do a thorough review of PR #145. I have three things to flag inline, "
            "then submit the review.\n\n"
            "1. src/auth.py, line 12: 'This breaks when `token` is None — add an "
            "early return.'\n"
            "2. src/auth.py, line 50: 'Use TOKEN_TTL_SECONDS constant from "
            "config.py instead of hard-coding 3600.'\n"
            "3. tests/test_auth.py, line 8: 'Add a test for the expired-token "
            "branch.'\n\n"
            "After the inline comments, submit a REQUEST_CHANGES review with "
            "body 'Three issues — see inline. Otherwise the structure is good.'\n\n"
            "Then leave a conversation comment on the PR: 'Heads up — the auth "
            "module also needs unit tests for the new code path. Happy to pair "
            "on it if useful.'"
        ),
        context=(
            "Repo: tensorzero/playground\n"
            "PR #145 is open. Diff touches src/auth.py and tests/test_auth.py."
        ),
        required_calls=(
            RequiredCall(
                op="gh.pr_review_comment",
                args={
                    "number": Eq(145),
                    "path": Contains("src/auth.py"),
                    "line": Eq(12),
                    "body": Contains("None"),
                },
            ),
            RequiredCall(
                op="gh.pr_review_comment",
                args={
                    "number": Eq(145),
                    "path": Contains("src/auth.py"),
                    "line": Eq(50),
                    "body": Contains("TOKEN_TTL_SECONDS"),
                },
            ),
            RequiredCall(
                op="gh.pr_review_comment",
                args={
                    "number": Eq(145),
                    "path": Contains("tests/test_auth.py"),
                    "line": Eq(8),
                    "body": Contains("expired"),
                },
            ),
            RequiredCall(
                op="gh.pr_review_submit",
                args={
                    "number": Eq(145),
                    "event": Eq("REQUEST_CHANGES"),
                    "body": Contains("inline"),
                },
            ),
            RequiredCall(
                op="gh.pr_comment",
                args={
                    "number": Eq(145),
                    "body": Contains("unit tests"),
                },
            ),
        ),
        strict_order=False,
        failure_triggers=(
            review_event_enum_mismatch(),
        ),
        note=(
            "Tests whether the model issues THREE distinct review comments "
            "(not one combined comment), then a separate verdict submission, "
            "then a separate conversation comment. The three confusable github "
            "tools all appear in one task. "
            "Multi-turn: same event='APPROVED' vs 'APPROVE' failure as M3 → "
            "tests lesson transfer for schema-invalid errors."
        ),
    ),
)
