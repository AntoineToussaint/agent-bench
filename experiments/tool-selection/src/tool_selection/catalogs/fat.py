"""Fat-granularity catalog: ~12 consolidated tools across the same 3 toolboxes.

Same capabilities as `narrow`, but related operations are merged into a single
tool with an `action` enum + optional args. Tests whether the model can pick
the right action and supply the right (action-specific) optional args.

The action enum on each tool is the lever — wider enum + more conditionally-
required args ⇒ more schema mistakes; smaller schema ⇒ fewer input tokens.
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


# ---------- filesystem (4 fat tools) ----------

FS_TOOLS = (
    Tool(
        name="fs_read",
        toolbox="filesystem",
        description="Read the contents of a single file. Returns the full text, optionally restricted to a line range.",
        json_schema=_schema(
            {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            required=["path"],
        ),
    ),
    Tool(
        name="fs_write",
        toolbox="filesystem",
        description="Write content to a file. Pick the mode: 'create' fails if the file exists, 'overwrite' replaces existing content, 'append' adds to the end. Use this for any tracked-file modification.",
        json_schema=_schema(
            {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["create", "overwrite", "append"]},
            },
            required=["path", "content", "mode"],
        ),
    ),
    Tool(
        name="fs_organize",
        toolbox="filesystem",
        description="Filesystem organization actions: 'delete' a file, 'move' a file (rename), 'mkdir' to create a directory, or 'list' a directory's contents. Provide the matching args for the chosen action.",
        json_schema=_schema(
            {
                "action": {"type": "string", "enum": ["delete", "move", "mkdir", "list"]},
                "path": {"type": "string", "description": "Primary path for the action."},
                "destination": {"type": "string", "description": "Required for action='move'."},
                "show_hidden": {"type": "boolean", "description": "For action='list': include dotfiles."},
            },
            required=["action", "path"],
        ),
    ),
    Tool(
        name="fs_search",
        toolbox="filesystem",
        description="Find files matching a pattern. Set in_content=true for grep-style search inside file contents; otherwise it is a glob over filenames.",
        json_schema=_schema(
            {
                "pattern": {"type": "string"},
                "in_content": {"type": "boolean", "description": "True = grep inside files; false = glob on filenames."},
                "directory": {"type": "string"},
                "file_glob": {"type": "string", "description": "When in_content=true, restrict to files matching this glob."},
            },
            required=["pattern"],
        ),
    ),
)


# ---------- git (4 fat tools) ----------

GIT_TOOLS = (
    Tool(
        name="git_local",
        toolbox="git",
        description="Inspect or modify local git state. Actions: 'status' (working tree summary), 'diff' (unstaged or staged diff), 'log' (commit history), 'show' (single commit contents), 'add' (stage files), 'reset' (unstage or reset to a ref).",
        json_schema=_schema(
            {
                "action": {"type": "string", "enum": ["status", "diff", "log", "show", "add", "reset"]},
                "paths": {"type": "array", "items": {"type": "string"}, "description": "For 'add' or 'reset': files to stage/unstage."},
                "staged": {"type": "boolean", "description": "For 'diff': show staged diff instead of working-tree diff."},
                "ref": {"type": "string", "description": "For 'show'/'reset': commit ref."},
                "n": {"type": "integer", "description": "For 'log': max commits."},
                "mode": {"type": "string", "enum": ["mixed", "soft", "hard"], "description": "For 'reset': reset mode (default mixed)."},
            },
            required=["action"],
        ),
    ),
    Tool(
        name="git_commit",
        toolbox="git",
        description="Create or amend a commit. action='commit' creates a new commit from staged changes (message required). action='amend' modifies the most recent commit — provide message to replace it, or no_edit=true to keep the existing message and add staged changes.",
        json_schema=_schema(
            {
                "action": {"type": "string", "enum": ["commit", "amend"]},
                "message": {"type": "string"},
                "no_edit": {"type": "boolean", "description": "For action='amend': keep the existing message."},
            },
            required=["action"],
        ),
    ),
    Tool(
        name="git_branch",
        toolbox="git",
        description="Branch management. Actions: 'create' (make a new branch), 'delete' (remove a branch), 'list' (enumerate branches), 'checkout' (switch to a branch or commit), 'merge' (merge a branch into the current one).",
        json_schema=_schema(
            {
                "action": {"type": "string", "enum": ["create", "delete", "list", "checkout", "merge"]},
                "name": {"type": "string", "description": "Branch name (required for create/delete/checkout/merge)."},
                "from_ref": {"type": "string", "description": "For 'create': base ref."},
                "force": {"type": "boolean", "description": "For 'delete': force delete unmerged branch."},
                "create": {"type": "boolean", "description": "For 'checkout': create the branch if it doesn't exist."},
                "no_ff": {"type": "boolean", "description": "For 'merge': force a merge commit."},
                "remote": {"type": "boolean", "description": "For 'list': include remote-tracking branches."},
            },
            required=["action"],
        ),
    ),
    Tool(
        name="git_remote",
        toolbox="git",
        description="Communicate with a remote. action='push' uploads local commits; action='pull' fetches and merges.",
        json_schema=_schema(
            {
                "action": {"type": "string", "enum": ["push", "pull"]},
                "remote": {"type": "string", "description": "Remote name (default origin)."},
                "branch": {"type": "string"},
                "force": {"type": "boolean", "description": "For 'push' only."},
                "set_upstream": {"type": "boolean", "description": "For 'push': set the upstream tracking branch."},
            },
            required=["action"],
        ),
    ),
)


# ---------- github (4 fat tools) ----------

GH_TOOLS = (
    Tool(
        name="gh_pr",
        toolbox="github",
        description="Manage pull requests. Actions: 'create' (open a new PR — title and body required), 'view' (fetch metadata), 'list' (enumerate PRs), 'merge' (merge an open PR — method required), 'close' (close without merging).",
        json_schema=_schema(
            {
                "action": {"type": "string", "enum": ["create", "view", "list", "merge", "close"]},
                "number": {"type": "integer", "description": "For view/merge/close."},
                "title": {"type": "string", "description": "For 'create'."},
                "body": {"type": "string", "description": "For 'create': markdown PR description."},
                "base": {"type": "string", "description": "For 'create': base branch (default main)."},
                "head": {"type": "string", "description": "For 'create': head branch (default current)."},
                "draft": {"type": "boolean", "description": "For 'create'."},
                "method": {"type": "string", "enum": ["merge", "squash", "rebase"], "description": "For 'merge'."},
                "state": {"type": "string", "enum": ["open", "closed", "merged", "all"], "description": "For 'list'."},
            },
            required=["action"],
        ),
    ),
    Tool(
        name="gh_pr_feedback",
        toolbox="github",
        description=(
            "Post feedback on a pull request. Three distinct actions for three distinct comment types: "
            "'conversation' = general top-level discussion comment on the PR; "
            "'review_comment' = inline comment anchored to a specific line in the diff (requires path + line); "
            "'submit_review' = overall review verdict (APPROVE / REQUEST_CHANGES / COMMENT)."
        ),
        json_schema=_schema(
            {
                "action": {"type": "string", "enum": ["conversation", "review_comment", "submit_review"]},
                "number": {"type": "integer"},
                "body": {"type": "string"},
                "path": {"type": "string", "description": "For 'review_comment'."},
                "line": {"type": "integer", "description": "For 'review_comment'."},
                "side": {"type": "string", "enum": ["LEFT", "RIGHT"], "description": "For 'review_comment' (default RIGHT)."},
                "event": {"type": "string", "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"], "description": "For 'submit_review'."},
            },
            required=["action", "number"],
        ),
    ),
    Tool(
        name="gh_issue",
        toolbox="github",
        description="Manage issues. Actions: 'create' (file a new issue), 'view' (fetch one), 'list' (enumerate), 'comment' (post a comment on an issue — NOT a PR), 'close'.",
        json_schema=_schema(
            {
                "action": {"type": "string", "enum": ["create", "view", "list", "comment", "close"]},
                "number": {"type": "integer"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
                "assignees": {"type": "array", "items": {"type": "string"}},
                "comment": {"type": "string", "description": "For 'close': optional closing comment."},
            },
            required=["action"],
        ),
    ),
    Tool(
        name="gh_meta",
        toolbox="github",
        description="Read repository metadata and trigger workflow runs. action='repo_view' returns repo info; action='workflow_run' triggers a workflow_dispatch.",
        json_schema=_schema(
            {
                "action": {"type": "string", "enum": ["repo_view", "workflow_run"]},
                "repo": {"type": "string", "description": "For 'repo_view': owner/name (default current)."},
                "workflow": {"type": "string", "description": "For 'workflow_run'."},
                "ref": {"type": "string", "description": "For 'workflow_run'."},
                "inputs": {"type": "object", "description": "For 'workflow_run'."},
            },
            required=["action"],
        ),
    ),
)


fat_catalog = Catalog(
    granularity="fat",
    toolboxes=(
        Toolbox(name="filesystem", description=TOOLBOX_DESCRIPTIONS["filesystem"], tools=FS_TOOLS),
        Toolbox(name="git", description=TOOLBOX_DESCRIPTIONS["git"], tools=GIT_TOOLS),
        Toolbox(name="github", description=TOOLBOX_DESCRIPTIONS["github"], tools=GH_TOOLS),
    ),
)
