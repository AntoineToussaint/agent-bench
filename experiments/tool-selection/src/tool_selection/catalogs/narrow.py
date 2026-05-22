"""Narrow-granularity catalog: ~40 small tools across 3 toolboxes.

Includes intentionally-confusable sibling tools to test whether the model
picks the right specific tool when several are semantically nearby:
  - git_commit vs git_commit_amend
  - gh_pr_comment vs gh_pr_review_comment vs gh_pr_review_submit
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
        description="Read the contents of a single file. Returns the full text, optionally restricted to a line range. Errors if the file does not exist.",
        json_schema=_schema(
            {
                "path": {"type": "string", "description": "Path to the file (absolute or relative to repo root)."},
                "start_line": {"type": "integer", "description": "Optional 1-indexed first line to return."},
                "end_line": {"type": "integer", "description": "Optional 1-indexed last line to return (inclusive)."},
            },
            required=["path"],
        ),
    ),
    Tool(
        name="write_file",
        toolbox="filesystem",
        description="Write content to a file, overwriting any existing contents. Creates parent directories if needed. Use create_file if you want to fail when the file already exists.",
        json_schema=_schema(
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            required=["path", "content"],
        ),
    ),
    Tool(
        name="create_file",
        toolbox="filesystem",
        description="Create a new file with the given content. Fails if the file already exists. Use this when you want to guard against accidental overwrites.",
        json_schema=_schema(
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            required=["path", "content"],
        ),
    ),
    Tool(
        name="append_to_file",
        toolbox="filesystem",
        description="Append content to the end of an existing file. Creates the file if it does not exist. Does not add a leading newline — include one in content if needed.",
        json_schema=_schema(
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            required=["path", "content"],
        ),
    ),
    Tool(
        name="delete_file",
        toolbox="filesystem",
        description="Delete a file from the working tree. Does not stage the deletion in git — follow with git_add to stage. Errors if the path is a directory or does not exist.",
        json_schema=_schema(
            {"path": {"type": "string"}},
            required=["path"],
        ),
    ),
    Tool(
        name="list_directory",
        toolbox="filesystem",
        description="List the immediate contents of a directory. Returns file and subdirectory names. Use glob_files for recursive pattern matching.",
        json_schema=_schema(
            {
                "path": {"type": "string"},
                "show_hidden": {"type": "boolean", "description": "Include dotfiles in the listing."},
            },
            required=["path"],
        ),
    ),
    Tool(
        name="create_directory",
        toolbox="filesystem",
        description="Create a new directory, including parent directories as needed. No-op if the directory already exists.",
        json_schema=_schema(
            {"path": {"type": "string"}},
            required=["path"],
        ),
    ),
    Tool(
        name="move_file",
        toolbox="filesystem",
        description="Move or rename a file or directory. Use this for renames; do not delete + write. Does not stage the rename in git.",
        json_schema=_schema(
            {
                "source": {"type": "string"},
                "destination": {"type": "string"},
            },
            required=["source", "destination"],
        ),
    ),
    Tool(
        name="glob_files",
        toolbox="filesystem",
        description="Find files matching a glob pattern (e.g. 'src/**/*.py'). Returns matching paths. Use grep_files instead to search inside file contents.",
        json_schema=_schema(
            {
                "pattern": {"type": "string"},
                "directory": {"type": "string", "description": "Root directory for the search (default: repo root)."},
            },
            required=["pattern"],
        ),
    ),
    Tool(
        name="run_tests",
        toolbox="filesystem",
        description="Run pytest against the given test_path (relative to project root, must start with 'tests/'). Returns the pytest output.",
        json_schema=_schema(
            {
                "test_path": {"type": "string", "description": "Path relative to project root (e.g. 'tests/test_auth.py')."},
                "verbose": {"type": "boolean"},
            },
            required=["test_path"],
        ),
    ),
    Tool(
        name="grep_files",
        toolbox="filesystem",
        description="Search for a regex pattern inside file contents and return matching lines with their file paths. Use glob_files instead to match by filename only.",
        json_schema=_schema(
            {
                "pattern": {"type": "string", "description": "Regular expression to search for."},
                "directory": {"type": "string"},
                "file_glob": {"type": "string", "description": "Restrict search to files matching this glob."},
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
        description="Show the working tree status: staged, unstaged, and untracked files. Read-only; safe to call any time.",
        json_schema=_schema({}),
    ),
    Tool(
        name="git_diff",
        toolbox="git",
        description="Show the diff of changes. By default shows unstaged changes; set staged=true to show what would be committed. Pass a path to scope to a single file.",
        json_schema=_schema(
            {
                "path": {"type": "string"},
                "staged": {"type": "boolean", "description": "Show staged (cached) diff instead of working-tree diff."},
            }
        ),
    ),
    Tool(
        name="git_log",
        toolbox="git",
        description="Show recent commit history on the current branch. Limit with n (default 20). Optional author and since filters.",
        json_schema=_schema(
            {
                "n": {"type": "integer"},
                "author": {"type": "string"},
                "since": {"type": "string", "description": "e.g. '2 weeks ago' or '2026-04-01'."},
            }
        ),
    ),
    Tool(
        name="git_show",
        toolbox="git",
        description="Show the contents and diff of a specific commit, tag, or ref.",
        json_schema=_schema(
            {"ref": {"type": "string", "description": "Commit SHA, ref name, or HEAD~N."}},
            required=["ref"],
        ),
    ),
    Tool(
        name="git_add",
        toolbox="git",
        description="Stage changes for commit. Accepts one or more paths (use '.' for everything in the working directory). Required before git_commit.",
        json_schema=_schema(
            {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Paths to stage. Use ['.'] to stage all changes.",
                }
            },
            required=["paths"],
        ),
    ),
    Tool(
        name="git_reset",
        toolbox="git",
        description="Unstage files (default behavior) or reset the index/working tree. Use mode='hard' only when you intend to discard uncommitted changes.",
        json_schema=_schema(
            {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "Files to unstage. Omit to reset all."},
                "mode": {"type": "string", "enum": ["mixed", "soft", "hard"], "description": "Reset mode (default mixed)."},
                "ref": {"type": "string", "description": "Commit to reset to (default HEAD)."},
            }
        ),
    ),
    Tool(
        name="git_commit",
        toolbox="git",
        description="Create a new commit with the staged changes and the given message. Fails if there are no staged changes. Does NOT amend; use git_commit_amend to modify the most recent commit.",
        json_schema=_schema(
            {"message": {"type": "string", "description": "Commit message. Multi-line supported."}},
            required=["message"],
        ),
    ),
    Tool(
        name="git_commit_amend",
        toolbox="git",
        description="Amend the most recent commit, either by changing its message or by adding currently-staged changes to it. Pass no_edit=true to keep the existing message. Rewrites history — do not use on commits that have been pushed and shared.",
        json_schema=_schema(
            {
                "message": {"type": "string", "description": "Replacement commit message. Omit when no_edit=true."},
                "no_edit": {"type": "boolean", "description": "Keep the existing commit message; only add staged changes."},
            }
        ),
    ),
    Tool(
        name="git_branch_create",
        toolbox="git",
        description="Create a new branch. Does NOT check it out — use git_checkout with create=true to create and switch in one step. Optionally branch off a specific ref.",
        json_schema=_schema(
            {
                "name": {"type": "string"},
                "from_ref": {"type": "string", "description": "Commit or branch to base the new branch on (default HEAD)."},
            },
            required=["name"],
        ),
    ),
    Tool(
        name="git_branch_delete",
        toolbox="git",
        description="Delete a local branch. Fails if the branch has unmerged commits unless force=true.",
        json_schema=_schema(
            {
                "name": {"type": "string"},
                "force": {"type": "boolean"},
            },
            required=["name"],
        ),
    ),
    Tool(
        name="git_branch_list",
        toolbox="git",
        description="List local branches. Set remote=true to include remote-tracking branches.",
        json_schema=_schema(
            {"remote": {"type": "boolean"}}
        ),
    ),
    Tool(
        name="git_checkout",
        toolbox="git",
        description="Switch to an existing branch, tag, or commit. Set create=true to create and switch in one step (equivalent to git checkout -b).",
        json_schema=_schema(
            {
                "ref": {"type": "string"},
                "create": {"type": "boolean", "description": "Create the branch before switching."},
            },
            required=["ref"],
        ),
    ),
    Tool(
        name="git_merge",
        toolbox="git",
        description="Merge another branch into the current branch. Set no_ff=true to force a merge commit even when fast-forward is possible.",
        json_schema=_schema(
            {
                "branch": {"type": "string"},
                "no_ff": {"type": "boolean"},
            },
            required=["branch"],
        ),
    ),
    Tool(
        name="git_push",
        toolbox="git",
        description="Push local commits to a remote. Defaults to the upstream of the current branch. Set force=true only when you knowingly want to overwrite remote history.",
        json_schema=_schema(
            {
                "remote": {"type": "string", "description": "Remote name (default origin)."},
                "branch": {"type": "string", "description": "Local branch to push (default current)."},
                "force": {"type": "boolean"},
                "set_upstream": {"type": "boolean", "description": "Set the upstream tracking branch (-u)."},
            }
        ),
    ),
    Tool(
        name="git_pull",
        toolbox="git",
        description="Fetch from a remote and merge into the current branch. Use git_checkout + git_merge if you need finer control.",
        json_schema=_schema(
            {
                "remote": {"type": "string"},
                "branch": {"type": "string"},
            }
        ),
    ),
)


# ---------- github ----------

GH_TOOLS = (
    Tool(
        name="gh_pr_create",
        toolbox="github",
        description="Open a new pull request from the current branch (or an explicit head branch) into a base branch (default main). Title and body are required; body supports markdown.",
        json_schema=_schema(
            {
                "title": {"type": "string"},
                "body": {"type": "string", "description": "PR description in markdown."},
                "base": {"type": "string", "description": "Base branch (default main)."},
                "head": {"type": "string", "description": "Head branch (default current)."},
                "draft": {"type": "boolean"},
            },
            required=["title", "body"],
        ),
    ),
    Tool(
        name="gh_pr_view",
        toolbox="github",
        description="Fetch the metadata and body of a pull request by number. Read-only.",
        json_schema=_schema(
            {"number": {"type": "integer"}},
            required=["number"],
        ),
    ),
    Tool(
        name="gh_pr_list",
        toolbox="github",
        description="List pull requests. Filterable by state, author, and label.",
        json_schema=_schema(
            {
                "state": {"type": "string", "enum": ["open", "closed", "merged", "all"]},
                "author": {"type": "string"},
                "label": {"type": "string"},
            }
        ),
    ),
    Tool(
        name="gh_pr_comment",
        toolbox="github",
        description="Post a general conversation comment on a pull request (top-level discussion, not anchored to any specific line). Use gh_pr_review_comment for an inline comment on a specific line of the diff.",
        json_schema=_schema(
            {
                "number": {"type": "integer"},
                "body": {"type": "string"},
            },
            required=["number", "body"],
        ),
    ),
    Tool(
        name="gh_pr_review_comment",
        toolbox="github",
        description="Post an inline review comment anchored to a specific line of a file in a pull request's diff. Distinct from gh_pr_comment (general discussion) and gh_pr_review_submit (overall review verdict).",
        json_schema=_schema(
            {
                "number": {"type": "integer"},
                "body": {"type": "string"},
                "path": {"type": "string", "description": "File the comment is anchored to."},
                "line": {"type": "integer", "description": "Line number in the file."},
                "side": {"type": "string", "enum": ["LEFT", "RIGHT"], "description": "LEFT = old version, RIGHT = new version (default RIGHT)."},
            },
            required=["number", "body", "path", "line"],
        ),
    ),
    Tool(
        name="gh_pr_review_submit",
        toolbox="github",
        description="Submit an overall pull request review with a verdict: APPROVE, REQUEST_CHANGES, or COMMENT. Optionally attach a body summarizing the review. Inline comments are made separately with gh_pr_review_comment.",
        json_schema=_schema(
            {
                "number": {"type": "integer"},
                "event": {"type": "string", "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"]},
                "body": {"type": "string"},
            },
            required=["number", "event"],
        ),
    ),
    Tool(
        name="gh_pr_merge",
        toolbox="github",
        description="Merge a pull request. Pick the merge method: merge (merge commit), squash (single squashed commit), or rebase (replay commits onto base).",
        json_schema=_schema(
            {
                "number": {"type": "integer"},
                "method": {"type": "string", "enum": ["merge", "squash", "rebase"]},
            },
            required=["number", "method"],
        ),
    ),
    Tool(
        name="gh_pr_close",
        toolbox="github",
        description="Close a pull request without merging. The branch is not deleted.",
        json_schema=_schema(
            {"number": {"type": "integer"}},
            required=["number"],
        ),
    ),
    Tool(
        name="gh_issue_create",
        toolbox="github",
        description="File a new issue. Body is markdown. Optional labels are applied at creation time.",
        json_schema=_schema(
            {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "assignees": {"type": "array", "items": {"type": "string"}},
            },
            required=["title", "body"],
        ),
    ),
    Tool(
        name="gh_issue_view",
        toolbox="github",
        description="Fetch the metadata and body of an issue by number. Read-only.",
        json_schema=_schema(
            {"number": {"type": "integer"}},
            required=["number"],
        ),
    ),
    Tool(
        name="gh_issue_comment",
        toolbox="github",
        description="Post a comment on an issue. Use gh_pr_comment for comments on pull requests (they are a different API surface despite the UI being similar).",
        json_schema=_schema(
            {
                "number": {"type": "integer"},
                "body": {"type": "string"},
            },
            required=["number", "body"],
        ),
    ),
    Tool(
        name="gh_issue_close",
        toolbox="github",
        description="Close an issue. Optionally include a comment explaining the reason.",
        json_schema=_schema(
            {
                "number": {"type": "integer"},
                "comment": {"type": "string"},
            },
            required=["number"],
        ),
    ),
    Tool(
        name="gh_repo_view",
        toolbox="github",
        description="Fetch repository metadata: default branch, description, topics, latest release. Read-only.",
        json_schema=_schema(
            {"repo": {"type": "string", "description": "owner/name (default: current repo)."}}
        ),
    ),
    Tool(
        name="gh_workflow_run",
        toolbox="github",
        description="Trigger a GitHub Actions workflow run on a given ref. The workflow must support workflow_dispatch.",
        json_schema=_schema(
            {
                "workflow": {"type": "string", "description": "Workflow filename or name."},
                "ref": {"type": "string", "description": "Branch or tag to run on (default default branch)."},
                "inputs": {"type": "object", "description": "Workflow input parameters."},
            },
            required=["workflow"],
        ),
    ),
)


narrow_catalog = Catalog(
    granularity="narrow",
    toolboxes=(
        Toolbox(name="filesystem", description=TOOLBOX_DESCRIPTIONS["filesystem"], tools=FS_TOOLS),
        Toolbox(name="git", description=TOOLBOX_DESCRIPTIONS["git"], tools=GIT_TOOLS),
        Toolbox(name="github", description=TOOLBOX_DESCRIPTIONS["github"], tools=GH_TOOLS),
    ),
)
