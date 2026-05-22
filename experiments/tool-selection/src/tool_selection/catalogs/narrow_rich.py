"""Narrow catalog, RICH descriptions — mimics production MCP servers.

Same 39 tools and the same JSON schemas as `narrow.py`, but with multi-paragraph
tool descriptions (WHEN TO USE / WHEN NOT TO USE / BEHAVIOR / ERRORS / EXAMPLE
sections) and fully-documented arguments. Average description length ~700
chars, roughly matching the GitHub MCP / Linear MCP style.

Purpose: directly test whether two-phase pipelines pay off when description
text is large enough that putting all N descriptions in a one-phase prompt
becomes a real cost. The thin `narrow.py` catalog has ~125-char descriptions
that don't stress the one-phase prompt; this catalog does.
"""

from __future__ import annotations

from tool_selection.types import Catalog, Tool, Toolbox

from ._descriptions import TOOLBOX_DESCRIPTIONS


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


# ---------- filesystem ----------

FS_TOOLS = (
    Tool(
        name="read_file",
        toolbox="filesystem",
        description=(
            "Read the contents of a single file from the local working tree and return its text.\n\n"
            "WHEN TO USE: Inspecting a source file you intend to modify, checking the current state "
            "of a config or markdown file, or extracting a known line range for review. Read-only — "
            "safe to use as a discovery step before a write.\n\n"
            "WHEN NOT TO USE: To list directory contents (use list_directory or glob_files); to "
            "search by content (use grep_files); to read a deleted-and-staged file (the working "
            "tree no longer has it — use git_show with HEAD:path instead).\n\n"
            "BEHAVIOR: Reads the file at the given path as UTF-8 text and returns the full content "
            "by default. If start_line and/or end_line are provided, returns only that 1-indexed "
            "inclusive range (line 1 is the first line). Trailing newline of the file is preserved.\n\n"
            "ERRORS: Raises if the path does not exist, points to a directory, or is unreadable "
            "(permissions). The error message includes the path.\n\n"
            "EXAMPLE:\n"
            "  read_file(path='src/auth.py')\n"
            "  read_file(path='pyproject.toml', start_line=10, end_line=30)"
        ),
        json_schema=_schema(
            {
                "path": {
                    "type": "string",
                    "description": (
                        "Filesystem path to the file. Can be absolute or relative to the repo root. "
                        "Use forward slashes even on Windows. Examples: 'src/auth.py', "
                        "'tests/integration/test_login.py', '/etc/hostname'."
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "description": (
                        "Optional 1-indexed first line to return (inclusive). Line 1 is the first "
                        "line of the file. If omitted, reading starts at line 1."
                    ),
                },
                "end_line": {
                    "type": "integer",
                    "description": (
                        "Optional 1-indexed last line to return (inclusive). If omitted, reads to "
                        "end of file. Must be >= start_line if both are provided."
                    ),
                },
            },
            required=["path"],
        ),
    ),
    Tool(
        name="write_file",
        toolbox="filesystem",
        description=(
            "Write content to a file, replacing the file's entire contents. Creates the file (and "
            "any missing parent directories) if it does not exist.\n\n"
            "WHEN TO USE: Replacing a file you've fully composed in memory; making a large edit "
            "where it's easier to write the whole new version than to splice. After this call, "
            "you'll typically need to git_add the path before committing.\n\n"
            "WHEN NOT TO USE: When the file might already exist and overwriting would be a mistake "
            "(use create_file, which fails on existing). To append rather than replace (use "
            "append_to_file). To rename a file (use move_file).\n\n"
            "BEHAVIOR: Truncates the existing file (if any) and writes `content` as UTF-8. Creates "
            "missing parent directories. Preserves no metadata from any prior version. Returns "
            "the path written.\n\n"
            "ERRORS: Raises on permission denied or if `path` resolves to an existing directory.\n\n"
            "EXAMPLE:\n"
            "  write_file(path='src/config.py', content='from pathlib import Path\\n...')\n"
            "  write_file(path='new/file.txt', content='hello')  # creates new/ dir"
        ),
        json_schema=_schema(
            {
                "path": {
                    "type": "string",
                    "description": (
                        "Destination path for the file. Parent directories are created as needed. "
                        "Existing file at this path will be silently overwritten."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "The full new content of the file as UTF-8 text. Include a trailing newline "
                        "if you want one — the tool does not add one for you. Use \\n for line breaks."
                    ),
                },
            },
            required=["path", "content"],
        ),
    ),
    Tool(
        name="create_file",
        toolbox="filesystem",
        description=(
            "Create a new file with the given content. Fails if a file already exists at that path.\n\n"
            "WHEN TO USE: You're creating a genuinely new file — a new module, a new test, a new "
            "config — and want a hard guarantee that you won't silently overwrite anything. The "
            "safer alternative to write_file when you expect the path to not exist.\n\n"
            "WHEN NOT TO USE: You want to replace existing content (use write_file). You want to "
            "add to an existing file (use append_to_file).\n\n"
            "BEHAVIOR: Identical to write_file but errors out if the destination already exists. "
            "Creates missing parent directories. UTF-8 encoded.\n\n"
            "ERRORS: Raises FileExistsError if the path is already a file or directory. Raises on "
            "permission denied.\n\n"
            "EXAMPLE:\n"
            "  create_file(path='src/themes/dark.css', content=\":root { --bg: #0d1117; }\\n\")"
        ),
        json_schema=_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Path for the new file. Must not already exist.",
                },
                "content": {
                    "type": "string",
                    "description": "UTF-8 content for the new file. Include a trailing newline if desired.",
                },
            },
            required=["path", "content"],
        ),
    ),
    Tool(
        name="append_to_file",
        toolbox="filesystem",
        description=(
            "Append text to the end of an existing file, or create the file if it does not exist.\n\n"
            "WHEN TO USE: Adding a new entry to a log, a new import line to a barrel file, a new "
            "row to a CSV, an @import line to a stylesheet aggregator. When the rest of the file "
            "should stay unchanged and you want only your content tacked onto the end.\n\n"
            "WHEN NOT TO USE: To insert into the middle of a file (use read_file + write_file with "
            "the full new content). To overwrite (use write_file).\n\n"
            "BEHAVIOR: Opens the file in append mode and writes `content` verbatim. Does NOT add "
            "a leading newline — if you want a new line, include '\\n' at the start of your content. "
            "Creates the file (and missing parent directories) if it doesn't exist.\n\n"
            "ERRORS: Raises on permission denied or if path resolves to a directory.\n\n"
            "EXAMPLE:\n"
            "  append_to_file(path='src/themes/index.css', content=\"\\n@import './dark.css';\\n\")"
        ),
        json_schema=_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Path of the file to append to. Created if it does not exist.",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Text to append. NOT prefixed with a newline — include '\\n' at the start "
                        "of your content if you want one."
                    ),
                },
            },
            required=["path", "content"],
        ),
    ),
    Tool(
        name="delete_file",
        toolbox="filesystem",
        description=(
            "Delete a single file from the working tree.\n\n"
            "WHEN TO USE: Removing an obsolete source file as part of a refactor or cleanup, "
            "deleting a generated artifact, removing a test that's been replaced. Follow with "
            "git_add of the path to stage the deletion for commit.\n\n"
            "WHEN NOT TO USE: Removing a directory (this tool only handles files; there is no "
            "directory-delete tool surfaced — delete contents file-by-file and the parent will "
            "remain). Renaming a file (use move_file).\n\n"
            "BEHAVIOR: Unlinks the file from the working tree. Does NOT stage the deletion in "
            "git — you must follow with git_add for the change to be committable.\n\n"
            "ERRORS: Raises if the path does not exist, is a directory, or permission is denied.\n\n"
            "EXAMPLE:\n"
            "  delete_file(path='src/legacy/old_module.py')"
        ),
        json_schema=_schema(
            {"path": {"type": "string", "description": "Path of the file to delete."}},
            required=["path"],
        ),
    ),
    Tool(
        name="list_directory",
        toolbox="filesystem",
        description=(
            "List the immediate (non-recursive) contents of a single directory. Returns file and "
            "subdirectory names.\n\n"
            "WHEN TO USE: Quickly checking what's inside one directory, especially before "
            "creating or deleting children. Cheaper than glob_files when you only need one level.\n\n"
            "WHEN NOT TO USE: Walking a tree recursively (use glob_files with a pattern like "
            "'**/*'). Searching by file contents (use grep_files). Stat'ing a single file "
            "(use read_file or check directly with file_exists if available).\n\n"
            "BEHAVIOR: Lists entries in `path` and returns their basenames. Hidden files (those "
            "starting with '.') are excluded unless `show_hidden=true`. Symlinks are listed by "
            "name without resolution.\n\n"
            "ERRORS: Raises if `path` does not exist or is not a directory.\n\n"
            "EXAMPLE:\n"
            "  list_directory(path='src')\n"
            "  list_directory(path='.', show_hidden=True)"
        ),
        json_schema=_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Directory path to list. Must be an existing directory.",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "If true, includes dotfiles (.git, .env, etc). Defaults to false.",
                },
            },
            required=["path"],
        ),
    ),
    Tool(
        name="create_directory",
        toolbox="filesystem",
        description=(
            "Create a directory, including any missing parent directories. Idempotent — no-op if "
            "the directory already exists.\n\n"
            "WHEN TO USE: Setting up a new module folder, creating a tests/ subdirectory, etc. "
            "before placing files into it. Useful when subsequent create_file calls need a parent "
            "directory that doesn't yet exist (note: create_file/write_file create parents "
            "automatically, so this is often unnecessary — call it only when the parent is the "
            "actual goal).\n\n"
            "WHEN NOT TO USE: When you're about to create files in the directory anyway — file "
            "creation will make missing parent directories for you. When the directory definitely "
            "already exists per the surfaced context (calling this 'just to be safe' is wasted).\n\n"
            "BEHAVIOR: mkdir -p semantics: creates path and any missing parents, no-ops if path "
            "already exists as a directory. Errors only if path exists as a file.\n\n"
            "ERRORS: Raises if `path` exists but is a regular file (not a directory).\n\n"
            "EXAMPLE:\n"
            "  create_directory(path='src/themes')"
        ),
        json_schema=_schema(
            {"path": {"type": "string", "description": "Directory path to create (mkdir -p)."}},
            required=["path"],
        ),
    ),
    Tool(
        name="move_file",
        toolbox="filesystem",
        description=(
            "Move or rename a file or directory. The atomic primitive for renames.\n\n"
            "WHEN TO USE: Renaming a file (e.g. src/old_name.py -> src/new_name.py). Relocating a "
            "file to a different directory while keeping its content. Reorganizing source layout "
            "as part of a refactor.\n\n"
            "WHEN NOT TO USE: Combining delete + write_file — that creates TWO git changes "
            "(a delete and a new file) instead of ONE rename, losing history continuity. To copy "
            "a file (this tool moves; there is no surfaced copy tool — read + write_file is the "
            "fallback if you need to keep the original).\n\n"
            "BEHAVIOR: Calls the OS rename primitive. Works for both files and directories. "
            "Creates missing parent directories at the destination. Does NOT stage the rename "
            "in git — follow with git_add of both old and new paths (or just new path; git auto-"
            "detects the rename).\n\n"
            "ERRORS: Raises if source does not exist, if destination exists, or if source and "
            "destination are on different filesystems and rename cannot be atomic.\n\n"
            "EXAMPLE:\n"
            "  move_file(source='src/old_helpers.py', destination='src/helpers.py')"
        ),
        json_schema=_schema(
            {
                "source": {
                    "type": "string",
                    "description": "Current path of the file or directory to move.",
                },
                "destination": {
                    "type": "string",
                    "description": (
                        "Target path. Must not already exist. Parent directories are created if "
                        "needed. To rename in place, change only the basename."
                    ),
                },
            },
            required=["source", "destination"],
        ),
    ),
    Tool(
        name="glob_files",
        toolbox="filesystem",
        description=(
            "Find files in the working tree matching a shell-style glob pattern.\n\n"
            "WHEN TO USE: Locating all files of a type ('src/**/*.py'), finding files with a "
            "specific name across the tree ('**/test_*.py'), enumerating top-level scripts "
            "('scripts/*.sh'). Returns paths, not file contents.\n\n"
            "WHEN NOT TO USE: Searching inside file contents (use grep_files). Listing one "
            "directory level (use list_directory — cheaper). Checking a single specific path "
            "(prefer read_file — its error tells you whether the file exists).\n\n"
            "BEHAVIOR: Matches `pattern` against the working tree (default: repo root; "
            "configurable via `directory`). Standard glob: '*' matches a single segment, '**' "
            "matches any number of segments, '?' matches one character, '[abc]' matches one "
            "character in a set. Hidden directories (.git, .venv) are excluded.\n\n"
            "ERRORS: Returns an empty result for patterns that match nothing; raises only if "
            "`directory` is not a valid path.\n\n"
            "EXAMPLE:\n"
            "  glob_files(pattern='src/**/*.py')\n"
            "  glob_files(pattern='*.toml')\n"
            "  glob_files(pattern='**/test_*.py', directory='tests')"
        ),
        json_schema=_schema(
            {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Shell-style glob: '*' (one segment), '**' (any number of segments), '?' "
                        "(one char), '[abc]' (char class). Examples: 'src/**/*.py', '*.toml'."
                    ),
                },
                "directory": {
                    "type": "string",
                    "description": "Root directory for the search. Defaults to the repo root.",
                },
            },
            required=["pattern"],
        ),
    ),
    Tool(
        name="bash",
        toolbox="filesystem",
        description=(
            "Execute a shell command and return its stdout, stderr, and exit code.\n\n"
            "WHEN TO USE: For any command-line operation that doesn't have a dedicated tool — "
            "running test suites, build commands, package managers, linters, scripts.\n\n"
            "BEHAVIOR: Runs the command via /bin/sh from the repository root. The command "
            "string is passed verbatim — you compose it. No shell expansion of $HOME or ~.\n\n"
            "ERRORS: Non-zero exit code is NOT an exception; it's returned as part of the "
            "result. You must inspect stderr / exit code to detect failures.\n\n"
            "EXAMPLE:\n"
            "  bash(command='pytest test_auth.py')\n"
            "  bash(command='npm run build')\n"
            "  bash(command='ruff check src/')"
        ),
        json_schema=_schema(
            {
                "command": {
                    "type": "string",
                    "description": (
                        "The shell command to run, exactly as you'd type it at a terminal. "
                        "Compose the full invocation including any arguments."
                    ),
                },
            },
            required=["command"],
        ),
    ),
    Tool(
        name="run_tests",
        toolbox="filesystem",
        description=(
            "Run the project's test suite (pytest under the hood).\n\n"
            "WHEN TO USE: Verifying a fix locally before committing; running just the affected "
            "tests after editing a module; sanity-checking that the green tests stay green.\n\n"
            "WHEN NOT TO USE: For non-test code execution — this only invokes pytest, not arbitrary "
            "shell commands.\n\n"
            "BEHAVIOR: Invokes `pytest <test_path>` from the project root. Returns the test "
            "output (pass/fail summary + any tracebacks).\n\n"
            "PATH FORMAT: test_path MUST be relative to the project root, starting with 'tests/'. "
            "Example: 'tests/test_auth.py' or 'tests/integration/' for a directory. Bare filenames "
            "without the 'tests/' prefix will be interpreted relative to the current working "
            "directory and pytest will report 'collected 0 items' because it can't find the file.\n\n"
            "ERRORS: Returns exit code + collected/failed counts. 'collected 0 items' usually "
            "means the path is wrong (most often: missing 'tests/' prefix).\n\n"
            "EXAMPLE:\n"
            "  run_tests(test_path='tests/test_auth.py')                 # one file\n"
            "  run_tests(test_path='tests/integration/')                 # a subdirectory\n"
            "  run_tests(test_path='tests/test_auth.py::test_login')     # one specific test"
        ),
        json_schema=_schema(
            {
                "test_path": {
                    "type": "string",
                    "description": (
                        "Path to the test file or directory, RELATIVE to the project root. "
                        "Must start with 'tests/' (or whatever the project's test directory is). "
                        "Bare filenames will fail with 'collected 0 items'."
                    ),
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Pass -v to pytest for one-line-per-test output.",
                },
            },
            required=["test_path"],
        ),
    ),
    Tool(
        name="grep_files",
        toolbox="filesystem",
        description=(
            "Search for a regular-expression pattern inside file contents and return matching "
            "lines with their file paths and line numbers.\n\n"
            "WHEN TO USE: Finding all references to a function name, locating a constant, "
            "auditing usages of a deprecated API, finding TODOs. Returns text matches.\n\n"
            "WHEN NOT TO USE: Matching by filename only (use glob_files — cheaper). Reading "
            "structured data like JSON or YAML — grep is line-based and won't follow nested "
            "structure. Searching binary files (results will be noisy).\n\n"
            "BEHAVIOR: Searches files under `directory` (or repo root) for lines matching the "
            "Python regex `pattern`. Returns up to ~200 matching lines with path and 1-indexed "
            "line number. Restrict files with `file_glob` (e.g. '*.py'). Hidden directories "
            "are excluded by default.\n\n"
            "ERRORS: Empty result for no matches; raises on invalid regex.\n\n"
            "EXAMPLE:\n"
            "  grep_files(pattern='def load_config')\n"
            "  grep_files(pattern='TODO|FIXME', file_glob='*.py')"
        ),
        json_schema=_schema(
            {
                "pattern": {
                    "type": "string",
                    "description": (
                        "Python regex. Anchor with ^ or $ if needed; otherwise matches anywhere "
                        "in a line. Use \\b for word boundaries. Examples: '\\bdef load_config\\b', "
                        "'TODO|FIXME', 'class \\w+\\(Exception\\)'."
                    ),
                },
                "directory": {
                    "type": "string",
                    "description": "Directory to search under. Defaults to repo root.",
                },
                "file_glob": {
                    "type": "string",
                    "description": (
                        "Restrict the search to files matching this glob (e.g. '*.py', "
                        "'src/**/*.ts'). Without this, all text files are searched."
                    ),
                },
            },
            required=["pattern"],
        ),
    ),
)


# ---------- git ----------

GIT_TOOLS = (
    Tool(
        name="git_status",
        toolbox="git",
        description=(
            "Show the working tree status: staged, unstaged, and untracked files.\n\n"
            "WHEN TO USE: Before deciding what to stage and commit; checking what's currently "
            "modified after an edit; verifying the working tree is clean before a branch switch. "
            "Read-only — always safe to call.\n\n"
            "WHEN NOT TO USE: When the surfaced task context already tells you what's modified — "
            "calling this just to confirm is wasted work in a one-shot setting.\n\n"
            "BEHAVIOR: Equivalent to `git status --short --branch`. Returns the branch name, "
            "ahead/behind counts, and a list of paths grouped by state (staged / unstaged / "
            "untracked / unmerged).\n\n"
            "ERRORS: Raises if the cwd is not a git repository.\n\n"
            "EXAMPLE:\n"
            "  git_status()"
        ),
        json_schema=_schema({}),
    ),
    Tool(
        name="git_diff",
        toolbox="git",
        description=(
            "Show the diff of changes — unstaged by default, or staged (cached) with "
            "`staged=true`.\n\n"
            "WHEN TO USE: Reviewing exactly what's about to be committed (with `staged=true`) or "
            "what's been edited but not staged (default). Useful for crafting a commit message "
            "or sanity-checking a refactor.\n\n"
            "WHEN NOT TO USE: To see committed changes — use git_show or git_log. To see "
            "non-text differences (binaries are reported as 'binary files differ'). When the task "
            "context already includes the diff.\n\n"
            "BEHAVIOR: Returns unified diff output. With `path`, scopes to a single file. With "
            "`staged=true`, shows index-vs-HEAD; default shows working-tree-vs-index.\n\n"
            "ERRORS: Empty result for no differences; raises if `path` is not a tracked file.\n\n"
            "EXAMPLE:\n"
            "  git_diff()\n"
            "  git_diff(staged=True)\n"
            "  git_diff(path='src/auth.py')"
        ),
        json_schema=_schema(
            {
                "path": {
                    "type": "string",
                    "description": "Restrict the diff to a single file path. Default: all files.",
                },
                "staged": {
                    "type": "boolean",
                    "description": (
                        "If true, shows the staged (cached) diff — what would be committed. "
                        "Default is false (working-tree changes not yet staged)."
                    ),
                },
            }
        ),
    ),
    Tool(
        name="git_log",
        toolbox="git",
        description=(
            "Show the recent commit history on the current branch.\n\n"
            "WHEN TO USE: Finding a recent commit by author or date, getting a SHA to reference, "
            "checking what's been merged. Read-only.\n\n"
            "WHEN NOT TO USE: To see the contents/diff of a specific commit (use git_show). To "
            "see history of a specific file (no per-file flag here; use git_show on the SHA).\n\n"
            "BEHAVIOR: Returns the last `n` commits (default 20) on the current branch with "
            "SHA, author, date, and subject line. Filterable by `author` (substring match on "
            "name or email) and `since` (a relative or absolute date string).\n\n"
            "ERRORS: Raises if cwd is not a git repo.\n\n"
            "EXAMPLE:\n"
            "  git_log(n=10)\n"
            "  git_log(author='Antoine', since='2 weeks ago')"
        ),
        json_schema=_schema(
            {
                "n": {
                    "type": "integer",
                    "description": "Max number of commits to return. Defaults to 20.",
                },
                "author": {
                    "type": "string",
                    "description": (
                        "Restrict to commits whose author name or email matches this substring."
                    ),
                },
                "since": {
                    "type": "string",
                    "description": (
                        "Show commits more recent than this date. Accepts relative ('2 weeks ago', "
                        "'yesterday') or ISO ('2026-04-01') formats."
                    ),
                },
            }
        ),
    ),
    Tool(
        name="git_show",
        toolbox="git",
        description=(
            "Show the metadata and diff of a specific commit, tag, or any ref.\n\n"
            "WHEN TO USE: Inspecting what changed in a known commit; checking the contents of a "
            "tag; comparing HEAD to its parent (HEAD~1).\n\n"
            "WHEN NOT TO USE: To see a list of commits (use git_log). To see uncommitted changes "
            "(use git_diff).\n\n"
            "BEHAVIOR: Returns the commit's SHA, author, date, message, and unified diff against "
            "its parent. For a tag, shows the tagged object.\n\n"
            "ERRORS: Raises if `ref` does not resolve.\n\n"
            "EXAMPLE:\n"
            "  git_show(ref='HEAD')\n"
            "  git_show(ref='abc1234')\n"
            "  git_show(ref='HEAD~3')"
        ),
        json_schema=_schema(
            {
                "ref": {
                    "type": "string",
                    "description": (
                        "Any git ref: commit SHA (full or abbreviated), branch name, tag, or "
                        "HEAD~N. Examples: 'HEAD', 'abc1234', 'v1.2.0', 'HEAD~3', 'main'."
                    ),
                }
            },
            required=["ref"],
        ),
    ),
    Tool(
        name="git_add",
        toolbox="git",
        description=(
            "Stage one or more paths for the next commit.\n\n"
            "WHEN TO USE: As the step before git_commit. Stage individual files when you want to "
            "commit only some changes, or use ['.'] to stage everything in the working directory.\n\n"
            "WHEN NOT TO USE: To unstage (use git_reset). After git_commit_amend with the changes "
            "already staged (amend includes whatever is currently staged).\n\n"
            "BEHAVIOR: Adds the named paths to the index. For directories, adds all contained "
            "changes recursively. For deletions, also stages the deletion (no separate 'remove' "
            "needed). Returns the list of paths staged.\n\n"
            "ERRORS: Raises on invalid path or if a path is outside the working tree.\n\n"
            "EXAMPLE:\n"
            "  git_add(paths=['src/auth.py'])\n"
            "  git_add(paths=['src/auth.py', 'tests/test_auth.py'])\n"
            "  git_add(paths=['.'])  # everything"
        ),
        json_schema=_schema(
            {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of paths to stage. Use ['.'] to stage everything. Paths can be "
                        "files or directories. Use forward slashes."
                    ),
                }
            },
            required=["paths"],
        ),
    ),
    Tool(
        name="git_reset",
        toolbox="git",
        description=(
            "Unstage paths (default), or move HEAD to a different ref (with `mode`).\n\n"
            "WHEN TO USE: 'I accidentally staged something I didn't mean to' — call with the "
            "paths to unstage. Or 'I want to undo the last 3 commits but keep the changes' — "
            "call with `ref='HEAD~3'` and `mode='soft'`.\n\n"
            "WHEN NOT TO USE: To discard uncommitted changes — that's `mode='hard'`, which is "
            "DESTRUCTIVE and loses work; do not call this unless the user explicitly asked.\n\n"
            "BEHAVIOR: Without arguments, unstages everything. With `paths`, unstages only those. "
            "With `ref`, moves HEAD to that ref; `mode` controls how the index and working tree "
            "are updated:\n"
            "  - 'mixed' (default): keep working tree, reset index\n"
            "  - 'soft': keep both working tree and index\n"
            "  - 'hard': DESTRUCTIVE — overwrite both with `ref`\n\n"
            "ERRORS: Raises if `ref` does not resolve.\n\n"
            "EXAMPLE:\n"
            "  git_reset()                       # unstage everything\n"
            "  git_reset(paths=['src/auth.py'])  # unstage one file\n"
            "  git_reset(ref='HEAD~1', mode='soft')  # undo last commit, keep changes staged"
        ),
        json_schema=_schema(
            {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific paths to unstage. Omit to unstage everything.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["mixed", "soft", "hard"],
                    "description": (
                        "How to update index and working tree. 'mixed' (default) resets index but "
                        "keeps working tree. 'soft' keeps both. 'hard' overwrites both — DESTRUCTIVE."
                    ),
                },
                "ref": {
                    "type": "string",
                    "description": "Commit ref to reset HEAD to. Default is HEAD (just unstage).",
                },
            }
        ),
    ),
    Tool(
        name="git_commit",
        toolbox="git",
        description=(
            "Create a new commit from the currently-staged changes.\n\n"
            "WHEN TO USE: After git_add, to record the staged changes as a new commit on the "
            "current branch. This is the canonical 'finalize my changes' step.\n\n"
            "WHEN NOT TO USE: To modify the most recent commit — that's git_commit_amend, NOT a "
            "new commit on top. To discard staged changes (use git_reset). When nothing is "
            "staged (will error).\n\n"
            "BEHAVIOR: Creates a single new commit pointing at the current HEAD's parent with the "
            "staged changes as its diff. Working-tree unstaged changes are NOT included. After "
            "the commit, HEAD advances and the index is empty (staged set clears).\n\n"
            "ERRORS: Fails immediately if there are no staged changes. Fails if a merge or rebase "
            "is in progress (resolve first). Fails if message is empty.\n\n"
            "EXAMPLE:\n"
            "  git_commit(message='fix: handle null config (#123)')\n"
            "  git_commit(message='feat(themes): add dark mode\\n\\nFirst pass: dark theme variables only.')"
        ),
        json_schema=_schema(
            {
                "message": {
                    "type": "string",
                    "description": (
                        "Commit message. Multi-line via \\n; first line is conventionally the "
                        "subject (≤50 chars, imperative mood), then a blank line, then optional "
                        "body. Conventional prefixes (feat:, fix:, chore:, refactor:, test:, "
                        "docs:) are recommended for changelog generation."
                    ),
                }
            },
            required=["message"],
        ),
    ),
    Tool(
        name="git_commit_amend",
        toolbox="git",
        description=(
            "Amend the most recent commit — either replace its message, or fold currently-staged "
            "changes into it, or both. Rewrites history.\n\n"
            "WHEN TO USE: 'Oops, typo in my last commit message' (provide a new `message`). "
            "'Forgot to include this file in the last commit' (stage it with git_add, then call "
            "with `no_edit=True`). Both edits in one call: provide a `message` and the staged "
            "changes are also folded in.\n\n"
            "WHEN NOT TO USE: On commits that have been PUSHED and SHARED — amending rewrites "
            "history, and a force-push would be needed (DANGEROUS, can clobber teammates' work). "
            "To create a new commit on top of the previous one (use git_commit).\n\n"
            "BEHAVIOR: Replaces the most recent commit. With `message`, the new commit gets the "
            "new message. With `no_edit=True`, keeps the existing message and just folds in "
            "staged changes. Without either, opens an editor — but in non-interactive mode this "
            "is an error; supply one of the args.\n\n"
            "ERRORS: Fails if HEAD has no commits, or if a merge/rebase is in progress.\n\n"
            "EXAMPLE:\n"
            "  git_commit_amend(message='fix: better message')  # change message only\n"
            "  git_commit_amend(no_edit=True)                    # fold staged changes in"
        ),
        json_schema=_schema(
            {
                "message": {
                    "type": "string",
                    "description": "New commit message. Omit if no_edit=True.",
                },
                "no_edit": {
                    "type": "boolean",
                    "description": (
                        "If true, keep the existing commit message unchanged; only fold in "
                        "currently-staged changes."
                    ),
                },
            }
        ),
    ),
    Tool(
        name="git_branch_create",
        toolbox="git",
        description=(
            "Create a new branch at a given ref (default HEAD). Does NOT switch to it.\n\n"
            "WHEN TO USE: Setting up a feature branch off main: create + then git_checkout. As "
            "the first half of a 'work on a new branch' workflow when you want to control "
            "branch creation explicitly.\n\n"
            "WHEN NOT TO USE: To both create and switch in one step (faster: git_checkout with "
            "`create=True`). To rename a branch (no surfaced tool; delete + create).\n\n"
            "BEHAVIOR: Creates the branch at `from_ref` (default HEAD) without affecting the "
            "working tree. You stay on whatever branch you were on.\n\n"
            "ERRORS: Fails if the branch name already exists or is invalid.\n\n"
            "EXAMPLE:\n"
            "  git_branch_create(name='feature/dark-mode')\n"
            "  git_branch_create(name='hotfix/race-cond', from_ref='main')"
        ),
        json_schema=_schema(
            {
                "name": {
                    "type": "string",
                    "description": (
                        "Branch name. Conventions: prefix with feature/, fix/, hotfix/, chore/. "
                        "No spaces; slashes and dashes are fine."
                    ),
                },
                "from_ref": {
                    "type": "string",
                    "description": "Ref to base the new branch on. Defaults to HEAD.",
                },
            },
            required=["name"],
        ),
    ),
    Tool(
        name="git_branch_delete",
        toolbox="git",
        description=(
            "Delete a local branch.\n\n"
            "WHEN TO USE: Cleaning up after merge, removing an abandoned experiment. Only "
            "affects the local repository; remote branches are unaffected.\n\n"
            "WHEN NOT TO USE: To delete the current branch (must switch away first). To delete "
            "a remote branch (no surfaced tool; would need a special push).\n\n"
            "BEHAVIOR: Removes the branch ref. Without `force`, refuses to delete branches with "
            "unmerged commits (safety). With `force=True`, deletes regardless — POTENTIAL DATA "
            "LOSS if the branch had unique commits not merged anywhere.\n\n"
            "ERRORS: Fails if branch does not exist, is currently checked out, or has unmerged "
            "commits and force is not set.\n\n"
            "EXAMPLE:\n"
            "  git_branch_delete(name='old-feature')\n"
            "  git_branch_delete(name='experiment', force=True)"
        ),
        json_schema=_schema(
            {
                "name": {"type": "string", "description": "Branch to delete."},
                "force": {
                    "type": "boolean",
                    "description": (
                        "If true, force-delete even branches with unmerged commits. DESTRUCTIVE."
                    ),
                },
            },
            required=["name"],
        ),
    ),
    Tool(
        name="git_branch_list",
        toolbox="git",
        description=(
            "List branches in the repository.\n\n"
            "WHEN TO USE: Discovery — checking what branches exist before creating one with a "
            "potentially duplicate name; verifying a branch exists before checking it out.\n\n"
            "WHEN NOT TO USE: When the surfaced task context already tells you the branch state.\n\n"
            "BEHAVIOR: Returns local branch names by default. With `remote=True`, also returns "
            "remote-tracking branches (e.g. origin/main). The current branch is marked.\n\n"
            "ERRORS: Raises if cwd is not a git repo.\n\n"
            "EXAMPLE:\n"
            "  git_branch_list()\n"
            "  git_branch_list(remote=True)"
        ),
        json_schema=_schema(
            {
                "remote": {
                    "type": "boolean",
                    "description": "If true, include remote-tracking branches (origin/*). Default false.",
                }
            }
        ),
    ),
    Tool(
        name="git_checkout",
        toolbox="git",
        description=(
            "Switch to an existing branch, tag, or commit, OR create a new branch and switch in "
            "one step (with `create=True`).\n\n"
            "WHEN TO USE: Moving between branches; starting work on a feature (with `create=True` "
            "for both-in-one). When you need to inspect a specific historic commit (provide a "
            "SHA — note this puts you in 'detached HEAD' state).\n\n"
            "WHEN NOT TO USE: To create a branch without switching (use git_branch_create). With "
            "`create=True` when the branch already exists (will fail).\n\n"
            "BEHAVIOR: Updates HEAD to point at `ref` and updates the working tree to match. "
            "With `create=True`, first creates `ref` as a branch (off current HEAD), then "
            "switches. If there are uncommitted changes that would be overwritten by the switch, "
            "the operation fails — stage or stash them first.\n\n"
            "ERRORS: Fails if `ref` does not exist (unless `create=True`); fails if uncommitted "
            "changes would be clobbered.\n\n"
            "EXAMPLE:\n"
            "  git_checkout(ref='main')\n"
            "  git_checkout(ref='feature/new-thing', create=True)\n"
            "  git_checkout(ref='abc1234')  # detached HEAD"
        ),
        json_schema=_schema(
            {
                "ref": {
                    "type": "string",
                    "description": "Branch, tag, or commit SHA to switch to.",
                },
                "create": {
                    "type": "boolean",
                    "description": (
                        "If true, create `ref` as a new branch off current HEAD before switching. "
                        "Fails if the branch already exists."
                    ),
                },
            },
            required=["ref"],
        ),
    ),
    Tool(
        name="git_merge",
        toolbox="git",
        description=(
            "Merge a named branch into the current branch.\n\n"
            "WHEN TO USE: Bringing changes from a topic branch into a long-lived branch (e.g. "
            "merging feature/X into main, or merging main back into a long-running feature "
            "branch to stay current). The local-repo equivalent of accepting a PR.\n\n"
            "WHEN NOT TO USE: To replay commits on top of a base (no surfaced rebase tool — "
            "merge is the only integration mechanism here). To merge the current branch into "
            "another (switch first, then merge).\n\n"
            "BEHAVIOR: Combines `branch` into the current branch. By default, fast-forwards when "
            "possible. With `no_ff=True`, always creates an explicit merge commit. Stops with a "
            "conflict if there are merge conflicts (no auto-resolve).\n\n"
            "ERRORS: Fails on merge conflicts (manual resolution needed — outside this tool's "
            "scope). Fails if the working tree has uncommitted changes that would be overwritten.\n\n"
            "EXAMPLE:\n"
            "  git_merge(branch='feature/new-thing')\n"
            "  git_merge(branch='main', no_ff=True)  # always create a merge commit"
        ),
        json_schema=_schema(
            {
                "branch": {
                    "type": "string",
                    "description": "Branch to merge into the current branch.",
                },
                "no_ff": {
                    "type": "boolean",
                    "description": (
                        "If true, always create a merge commit (no fast-forward). Useful for "
                        "preserving the topic-branch history in main."
                    ),
                },
            },
            required=["branch"],
        ),
    ),
    Tool(
        name="git_push",
        toolbox="git",
        description=(
            "Push local commits to a remote.\n\n"
            "WHEN TO USE: Publishing local commits after a commit. First push of a new branch "
            "(use `set_upstream=True` to track it). Sharing a hotfix with the team.\n\n"
            "WHEN NOT TO USE: With `force=True` unless the user explicitly asked — force-push can "
            "destroy teammates' commits. On commits that haven't been made yet (push only sends "
            "what's already been committed).\n\n"
            "BEHAVIOR: Sends the current branch's commits to `remote` (default origin). If the "
            "branch has no upstream, the push will fail unless `set_upstream=True`. With "
            "`set_upstream=True`, configures the local branch to track `<remote>/<branch>` so "
            "future pulls/pushes work without args.\n\n"
            "ERRORS: Fails with 'no upstream' if `set_upstream` is not set on a new branch. Fails "
            "if the remote rejects the push (non-fast-forward without force).\n\n"
            "EXAMPLE:\n"
            "  git_push()                          # push current branch to its upstream\n"
            "  git_push(set_upstream=True)         # first push of a new branch\n"
            "  git_push(remote='upstream', branch='main')"
        ),
        json_schema=_schema(
            {
                "remote": {
                    "type": "string",
                    "description": "Remote name. Defaults to 'origin'.",
                },
                "branch": {
                    "type": "string",
                    "description": "Local branch to push. Defaults to current branch.",
                },
                "force": {
                    "type": "boolean",
                    "description": (
                        "If true, force-push, overwriting remote history. DANGEROUS — never use "
                        "on shared branches like main/master."
                    ),
                },
                "set_upstream": {
                    "type": "boolean",
                    "description": (
                        "If true, set the upstream tracking branch (-u). Required on first push "
                        "of a new branch so future pushes/pulls work without args."
                    ),
                },
            }
        ),
    ),
    Tool(
        name="git_pull",
        toolbox="git",
        description=(
            "Fetch from a remote and merge into the current branch in one step.\n\n"
            "WHEN TO USE: Updating a long-lived branch (main) before branching off it. Pulling "
            "teammates' work into your local copy before you push.\n\n"
            "WHEN NOT TO USE: When you want finer control (fetch first, inspect, then merge). "
            "When you have uncommitted changes that would conflict (stage/commit/stash first).\n\n"
            "BEHAVIOR: Performs `git fetch` for the named remote (default origin), then merges "
            "the corresponding remote branch into the current local branch. With merge conflicts, "
            "stops with conflict markers — manual resolution required.\n\n"
            "ERRORS: Fails on merge conflicts; fails if working tree has uncommitted changes "
            "that would be overwritten.\n\n"
            "EXAMPLE:\n"
            "  git_pull()                         # fetch + merge from upstream\n"
            "  git_pull(remote='origin', branch='main')"
        ),
        json_schema=_schema(
            {
                "remote": {
                    "type": "string",
                    "description": "Remote name. Defaults to 'origin'.",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to pull. Defaults to the upstream of the current branch.",
                },
            }
        ),
    ),
)


# ---------- github ----------

GH_TOOLS = (
    Tool(
        name="gh_pr_create",
        toolbox="github",
        description=(
            "Open a new pull request from a head branch into a base branch on the current "
            "repository.\n\n"
            "WHEN TO USE: After pushing a feature branch with git_push, to open a PR for "
            "review. Provide title and body up front — the body is markdown and supports the "
            "usual GitHub-flavored extensions (issue refs like #123, mentions, code blocks, "
            "task lists).\n\n"
            "WHEN NOT TO USE: To comment on an existing PR (use gh_pr_comment). To open a PR "
            "in a different repo (this tool operates on the current repo). To re-open a closed "
            "PR (use gh_pr_view first to confirm number; no surfaced re-open tool).\n\n"
            "BEHAVIOR: Creates a PR from `head` (default: current branch) into `base` (default: "
            "the repo's default branch, typically main). Returns the new PR's number and URL. "
            "With `draft=True`, opens as a draft (cannot be merged until marked ready).\n\n"
            "ERRORS: Fails if `head` is not pushed to the remote, if `head` has no commits ahead "
            "of `base`, or if a PR already exists for this head→base pair.\n\n"
            "EXAMPLE:\n"
            "  gh_pr_create(title='feat: dark mode', body='Adds a dark theme...\\nFixes #42.')\n"
            "  gh_pr_create(title='WIP: refactor', body='Pulling auth out...', draft=True)"
        ),
        json_schema=_schema(
            {
                "title": {
                    "type": "string",
                    "description": (
                        "PR title. Should be short and descriptive — conventional commit prefix "
                        "(feat:, fix:) recommended."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": (
                        "PR description, markdown. Conventionally has a Summary section and "
                        "may reference issues with #N. Multi-line via \\n."
                    ),
                },
                "base": {
                    "type": "string",
                    "description": (
                        "Base branch the PR targets (the branch that will receive the changes). "
                        "Defaults to the repo's default branch."
                    ),
                },
                "head": {
                    "type": "string",
                    "description": (
                        "Head branch — the source of the changes. Defaults to the current branch. "
                        "Must already be pushed to the remote."
                    ),
                },
                "draft": {
                    "type": "boolean",
                    "description": (
                        "If true, open as a draft PR. Drafts cannot be merged until marked "
                        "ready-for-review, but CI runs and comments work normally."
                    ),
                },
            },
            required=["title", "body"],
        ),
    ),
    Tool(
        name="gh_pr_view",
        toolbox="github",
        description=(
            "Fetch the metadata and body of a specific pull request by number.\n\n"
            "WHEN TO USE: Looking up the title/body/author/state of a PR you'll act on — "
            "checking labels, checking if it's been merged, fetching the description. Read-only.\n\n"
            "WHEN NOT TO USE: When the surfaced task context already gives you the PR info. To "
            "list multiple PRs (use gh_pr_list).\n\n"
            "BEHAVIOR: Returns the PR's number, title, body, state (open/closed/merged), author, "
            "head and base branches, labels, and creation/update timestamps.\n\n"
            "ERRORS: Raises if the PR number does not exist in the current repo.\n\n"
            "EXAMPLE:\n"
            "  gh_pr_view(number=142)"
        ),
        json_schema=_schema(
            {
                "number": {
                    "type": "integer",
                    "description": "PR number in the current repo (the integer after the '#').",
                }
            },
            required=["number"],
        ),
    ),
    Tool(
        name="gh_pr_list",
        toolbox="github",
        description=(
            "List pull requests in the current repository with optional filters.\n\n"
            "WHEN TO USE: Finding all open PRs by a specific author, all PRs with a label, all "
            "PRs in any state. Useful for triage workflows.\n\n"
            "WHEN NOT TO USE: To inspect a single known PR (use gh_pr_view — faster). To list "
            "issues (use gh_issue_list, which is a separate API surface).\n\n"
            "BEHAVIOR: Returns a list of PRs matching the filters. Each entry includes number, "
            "title, state, author, labels, and timestamps. Default returns open PRs only.\n\n"
            "ERRORS: Raises if filter values are malformed (e.g. unknown state).\n\n"
            "EXAMPLE:\n"
            "  gh_pr_list(state='open')\n"
            "  gh_pr_list(author='octocat', state='all')\n"
            "  gh_pr_list(label='bug')"
        ),
        json_schema=_schema(
            {
                "state": {
                    "type": "string",
                    "enum": ["open", "closed", "merged", "all"],
                    "description": "PR state filter. Defaults to 'open'.",
                },
                "author": {
                    "type": "string",
                    "description": "Filter to PRs opened by this GitHub login (no '@').",
                },
                "label": {
                    "type": "string",
                    "description": "Filter to PRs with this label applied. Case-sensitive.",
                },
            }
        ),
    ),
    Tool(
        name="gh_pr_comment",
        toolbox="github",
        description=(
            "Post a general top-level conversation comment on a pull request.\n\n"
            "WHEN TO USE: General PR discussion — 'this is ready for re-review', 'I'll address the "
            "feedback this week', 'merging now'. Anything that ISN'T pinned to a specific line of "
            "the diff and ISN'T a review verdict.\n\n"
            "WHEN NOT TO USE: To leave an inline comment on a line of the diff — use "
            "gh_pr_review_comment (it requires `path` and `line` because it's anchored). To submit "
            "an overall review (APPROVE / REQUEST_CHANGES / COMMENT) — use gh_pr_review_submit. "
            "These three are commonly confused; pick the one whose anchoring matches your intent.\n\n"
            "BEHAVIOR: Posts the body as a comment on the PR's conversation tab (the same place "
            "issues have comments). Markdown supported. Shows up immediately in the timeline.\n\n"
            "ERRORS: Raises if PR number does not exist.\n\n"
            "EXAMPLE:\n"
            "  gh_pr_comment(number=142, body='Rebased onto main, ready for re-review.')"
        ),
        json_schema=_schema(
            {
                "number": {
                    "type": "integer",
                    "description": "PR number to comment on.",
                },
                "body": {
                    "type": "string",
                    "description": (
                        "Markdown body of the comment. Multi-line via \\n. Supports @mentions "
                        "and issue refs."
                    ),
                },
            },
            required=["number", "body"],
        ),
    ),
    Tool(
        name="gh_pr_review_comment",
        toolbox="github",
        description=(
            "Post an INLINE review comment anchored to a specific line of a file in a pull "
            "request's diff.\n\n"
            "WHEN TO USE: Leaving feedback on a specific line — 'this should handle None on line "
            "45', 'use the constant on line 50'. The comment appears in the PR's Files Changed "
            "view, pinned to the line.\n\n"
            "WHEN NOT TO USE: For a general top-level PR comment that ISN'T pinned to a line — "
            "use gh_pr_comment instead. To submit an overall review verdict — use "
            "gh_pr_review_submit. This tool is for the inline pin only; the review-submit step is "
            "separate. Three different APIs that look similar; pick based on anchoring:\n"
            "  - line-anchored          → gh_pr_review_comment (this tool)\n"
            "  - general PR discussion  → gh_pr_comment\n"
            "  - overall verdict        → gh_pr_review_submit\n\n"
            "BEHAVIOR: Creates an inline comment on the PR's diff at `path` line `line`. The "
            "comment can be a single comment or part of a pending review (see gh_pr_review_submit). "
            "`side` selects whether the line refers to the old version (LEFT) or new version "
            "(RIGHT) of the diff; default RIGHT.\n\n"
            "ERRORS: Raises if PR/path/line do not match a position in the diff.\n\n"
            "EXAMPLE:\n"
            "  gh_pr_review_comment(number=321, body='Handle the None case here.',\n"
            "                       path='src/parser.py', line=45)"
        ),
        json_schema=_schema(
            {
                "number": {"type": "integer", "description": "PR number."},
                "body": {
                    "type": "string",
                    "description": "Markdown comment body. Should reference what's wrong with the line.",
                },
                "path": {
                    "type": "string",
                    "description": "File the comment is anchored to (must appear in the PR's diff).",
                },
                "line": {
                    "type": "integer",
                    "description": (
                        "Line number in the file. With side=RIGHT (default), refers to the new "
                        "(after-change) version of the file."
                    ),
                },
                "side": {
                    "type": "string",
                    "enum": ["LEFT", "RIGHT"],
                    "description": (
                        "LEFT = the old (pre-change) version of the file; RIGHT = the new "
                        "(post-change) version. Default RIGHT. Use LEFT to comment on a line "
                        "that was removed or changed."
                    ),
                },
            },
            required=["number", "body", "path", "line"],
        ),
    ),
    Tool(
        name="gh_pr_review_submit",
        toolbox="github",
        description=(
            "Submit an OVERALL pull-request review with a verdict.\n\n"
            "WHEN TO USE: After leaving any inline review comments, submit the overall review with "
            "the verdict — APPROVE (sign off), REQUEST_CHANGES (block until addressed), or "
            "COMMENT (neither approve nor block, just feedback). One of three confusable tools; "
            "this is the verdict-level action.\n\n"
            "WHEN NOT TO USE: To leave a single line-anchored comment — use gh_pr_review_comment. "
            "For general PR discussion — use gh_pr_comment.\n\n"
            "BEHAVIOR: Submits a review of the PR with the chosen `event`. If a body is supplied, "
            "it becomes the overall review comment. Submitting changes the PR's review state "
            "and (for APPROVE/REQUEST_CHANGES) the merge-ready state.\n\n"
            "ERRORS: Raises if PR does not exist or if `event` is not one of the three values.\n\n"
            "EXAMPLE:\n"
            "  gh_pr_review_submit(number=321, event='REQUEST_CHANGES',\n"
            "                      body='A few edge cases — see inline comments.')\n"
            "  gh_pr_review_submit(number=321, event='APPROVE', body='LGTM!')"
        ),
        json_schema=_schema(
            {
                "number": {"type": "integer", "description": "PR number to review."},
                "event": {
                    "type": "string",
                    "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"],
                    "description": (
                        "Verdict. APPROVE = sign off; REQUEST_CHANGES = block until addressed; "
                        "COMMENT = neither, just feedback. Note: APPROVED is NOT a valid value — "
                        "use APPROVE."
                    ),
                },
                "body": {
                    "type": "string",
                    "description": (
                        "Optional markdown summary of the overall review. Often empty if all "
                        "feedback was in inline comments."
                    ),
                },
            },
            required=["number", "event"],
        ),
    ),
    Tool(
        name="gh_pr_merge",
        toolbox="github",
        description=(
            "Merge an open pull request.\n\n"
            "WHEN TO USE: A reviewed-and-approved PR is ready to land. The team's chosen merge "
            "strategy goes in `method`.\n\n"
            "WHEN NOT TO USE: On draft PRs (cannot be merged — mark ready first). On PRs with "
            "failing required checks (will fail). To close without merging (use gh_pr_close).\n\n"
            "BEHAVIOR: Merges the PR using the chosen strategy:\n"
            "  - 'merge'  → preserves all branch commits, adds a merge commit\n"
            "  - 'squash' → squashes branch commits into a single commit on base\n"
            "  - 'rebase' → replays branch commits onto base, no merge commit\n"
            "After merge, the head branch is NOT auto-deleted on the remote — that's a separate "
            "step.\n\n"
            "ERRORS: Fails if the PR is closed, is a draft, has unresolved required reviews, has "
            "failing required checks, or has merge conflicts.\n\n"
            "EXAMPLE:\n"
            "  gh_pr_merge(number=142, method='squash')\n"
            "  gh_pr_merge(number=142, method='merge')"
        ),
        json_schema=_schema(
            {
                "number": {"type": "integer", "description": "PR number to merge."},
                "method": {
                    "type": "string",
                    "enum": ["merge", "squash", "rebase"],
                    "description": (
                        "Merge strategy. 'merge' adds a merge commit (preserves history); "
                        "'squash' collapses to one commit; 'rebase' replays without a merge "
                        "commit."
                    ),
                },
            },
            required=["number", "method"],
        ),
    ),
    Tool(
        name="gh_pr_close",
        toolbox="github",
        description=(
            "Close a pull request without merging.\n\n"
            "WHEN TO USE: Abandoning a PR (decided not to ship it), or closing one in favor of "
            "another PR. The branch is NOT deleted by this action.\n\n"
            "WHEN NOT TO USE: To merge a PR (use gh_pr_merge). To temporarily mark something "
            "as not-ready (use draft via the GitHub UI).\n\n"
            "BEHAVIOR: Closes the PR; it can be re-opened later by the author or a maintainer. "
            "No code is merged.\n\n"
            "ERRORS: Raises if PR is already closed or merged.\n\n"
            "EXAMPLE:\n"
            "  gh_pr_close(number=142)"
        ),
        json_schema=_schema(
            {"number": {"type": "integer", "description": "PR number to close."}},
            required=["number"],
        ),
    ),
    Tool(
        name="gh_issue_create",
        toolbox="github",
        description=(
            "File a new issue in the current repository.\n\n"
            "WHEN TO USE: Recording a bug report, feature request, or any tracked work item. "
            "Optionally apply labels and assignees at creation time.\n\n"
            "WHEN NOT TO USE: To open a pull request (use gh_pr_create). To comment on an "
            "existing issue (use gh_issue_comment).\n\n"
            "BEHAVIOR: Creates an issue with the given title and body. Labels and assignees are "
            "applied at creation if provided. Returns the new issue's number and URL.\n\n"
            "ERRORS: Raises if a label or assignee does not exist in the repo.\n\n"
            "EXAMPLE:\n"
            "  gh_issue_create(title='Memory leak in worker pool',\n"
            "                  body='Repro: ...', labels=['bug'], assignees=['octocat'])"
        ),
        json_schema=_schema(
            {
                "title": {"type": "string", "description": "Short issue title."},
                "body": {
                    "type": "string",
                    "description": "Markdown body of the issue.",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Label names to apply at creation. Each label must already exist in the "
                        "repo (this tool does not create new labels)."
                    ),
                },
                "assignees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "GitHub logins to assign (no '@').",
                },
            },
            required=["title", "body"],
        ),
    ),
    Tool(
        name="gh_issue_view",
        toolbox="github",
        description=(
            "Fetch the metadata and body of an issue by number. Read-only.\n\n"
            "WHEN TO USE: Looking up issue details before commenting or closing.\n\n"
            "WHEN NOT TO USE: When the surfaced task context already gives you the issue info. "
            "To list issues (use gh_issue_list).\n\n"
            "BEHAVIOR: Returns the issue's number, title, body, state, author, labels, assignees, "
            "and timestamps.\n\n"
            "ERRORS: Raises if number does not exist.\n\n"
            "EXAMPLE:\n"
            "  gh_issue_view(number=87)"
        ),
        json_schema=_schema(
            {"number": {"type": "integer", "description": "Issue number."}},
            required=["number"],
        ),
    ),
    Tool(
        name="gh_issue_comment",
        toolbox="github",
        description=(
            "Post a comment on an existing issue.\n\n"
            "WHEN TO USE: Adding to the discussion of an issue.\n\n"
            "WHEN NOT TO USE: To comment on a pull request (use gh_pr_comment — same UI but "
            "different API surface). To close the issue with a comment (use gh_issue_close with "
            "its optional `comment` arg).\n\n"
            "BEHAVIOR: Posts a comment on the issue's timeline. Markdown supported.\n\n"
            "ERRORS: Raises if number does not exist or is a PR (PRs use a separate comment API).\n\n"
            "EXAMPLE:\n"
            "  gh_issue_comment(number=87, body='Confirmed the repro on staging.')"
        ),
        json_schema=_schema(
            {
                "number": {"type": "integer", "description": "Issue number to comment on."},
                "body": {"type": "string", "description": "Markdown comment body."},
            },
            required=["number", "body"],
        ),
    ),
    Tool(
        name="gh_issue_close",
        toolbox="github",
        description=(
            "Close an issue, optionally with a final comment.\n\n"
            "WHEN TO USE: Resolving an issue ('fixed in #142', 'duplicate of #50', "
            "'not-planned'). Provide a `comment` to leave a final explanation in the same step.\n\n"
            "WHEN NOT TO USE: To just comment without closing (use gh_issue_comment).\n\n"
            "BEHAVIOR: Marks the issue as closed. If `comment` is provided, posts it before "
            "closing so the closing context is visible.\n\n"
            "ERRORS: Raises if number is not an issue or is already closed.\n\n"
            "EXAMPLE:\n"
            "  gh_issue_close(number=87, comment='Fixed by #142.')"
        ),
        json_schema=_schema(
            {
                "number": {"type": "integer", "description": "Issue number to close."},
                "comment": {
                    "type": "string",
                    "description": "Optional final comment to post before closing.",
                },
            },
            required=["number"],
        ),
    ),
    Tool(
        name="gh_repo_view",
        toolbox="github",
        description=(
            "Fetch metadata about a repository: default branch, description, topics, latest "
            "release, etc. Read-only.\n\n"
            "WHEN TO USE: Confirming the default branch name before opening a PR; checking the "
            "repo's described purpose.\n\n"
            "WHEN NOT TO USE: When the surfaced task context already tells you what you need.\n\n"
            "BEHAVIOR: Returns the repo's default branch, description, topics, visibility, "
            "license, and latest release tag. Defaults to the current repo if `repo` is omitted.\n\n"
            "ERRORS: Raises if `repo` does not exist.\n\n"
            "EXAMPLE:\n"
            "  gh_repo_view()\n"
            "  gh_repo_view(repo='tensorzero/playground')"
        ),
        json_schema=_schema(
            {
                "repo": {
                    "type": "string",
                    "description": "owner/name. Defaults to the current repo.",
                }
            }
        ),
    ),
    Tool(
        name="gh_workflow_run",
        toolbox="github",
        description=(
            "Trigger a GitHub Actions workflow run on a given branch or tag.\n\n"
            "WHEN TO USE: Manually kicking off a workflow that supports `workflow_dispatch` — "
            "e.g. CI on a specific branch, a release pipeline, a deploy job. With `inputs`, pass "
            "any required workflow inputs.\n\n"
            "WHEN NOT TO USE: For workflows that only run on push/PR events (this tool requires "
            "`workflow_dispatch` to be configured). To check the status of a previous run (no "
            "surfaced status tool).\n\n"
            "BEHAVIOR: Triggers `workflow` to run on `ref` (default: default branch). Inputs map "
            "to whatever the workflow's `workflow_dispatch.inputs` block defines.\n\n"
            "ERRORS: Raises if the workflow doesn't exist or doesn't support workflow_dispatch.\n\n"
            "EXAMPLE:\n"
            "  gh_workflow_run(workflow='ci.yml', ref='develop')\n"
            "  gh_workflow_run(workflow='deploy.yml', ref='main', inputs={'env': 'prod'})"
        ),
        json_schema=_schema(
            {
                "workflow": {
                    "type": "string",
                    "description": (
                        "Workflow filename (e.g. 'ci.yml') or its display name. Must be under "
                        ".github/workflows/."
                    ),
                },
                "ref": {
                    "type": "string",
                    "description": "Branch or tag to run on. Defaults to the repo's default branch.",
                },
                "inputs": {
                    "type": "object",
                    "description": (
                        "Optional input parameters, matching the workflow's "
                        "`workflow_dispatch.inputs` schema."
                    ),
                },
            },
            required=["workflow"],
        ),
    ),
)


narrow_rich_catalog = Catalog(
    granularity="narrow-rich",
    toolboxes=(
        Toolbox(name="filesystem", description=TOOLBOX_DESCRIPTIONS["filesystem"], tools=FS_TOOLS),
        Toolbox(name="git", description=TOOLBOX_DESCRIPTIONS["git"], tools=GIT_TOOLS),
        Toolbox(name="github", description=TOOLBOX_DESCRIPTIONS["github"], tools=GH_TOOLS),
    ),
)
