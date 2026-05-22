"""Logical operation layer — granularity-agnostic op names that map to tools.

A Task is authored in terms of operations like 'git.commit'. The scorer
translates each operation into a (tool_name, extra_args) pair for the catalog
it's evaluating against. This keeps task definitions readable and prevents
duplicating the same task once for narrow and once for fat.

Convention: op names are dotted '<toolbox>.<verb>' or '<toolbox>.<verb_target>'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import Granularity


@dataclass(frozen=True)
class OpSpec:
    """How a logical operation lands in each catalog granularity."""

    narrow_tool: str
    fat_tool: str
    """The expected concrete tool name in each catalog."""

    fat_args: dict[str, Any] = field(default_factory=dict)
    """Extra args that must appear in the fat call but not the narrow call.
    Typically includes the action discriminator, e.g. {'action': 'commit'}."""

    narrow_args: dict[str, Any] = field(default_factory=dict)
    """Extra args that must appear in the narrow call (rare — used when
    narrow needs an explicit mode flag, e.g. write_file vs create_file)."""

    def resolve(self, granularity: Granularity) -> tuple[str, dict[str, Any]]:
        # The granularity dimension encodes tool granularity (narrow/fat) AND
        # description richness/size suffixes (-rich, -rich-80, -rich-150).
        # For op resolution only the narrow-vs-fat split matters: any granularity
        # whose name starts with "narrow" maps to narrow tools.
        if granularity.startswith("narrow"):
            return self.narrow_tool, dict(self.narrow_args)
        return self.fat_tool, dict(self.fat_args)


# ---------- filesystem ----------

FS_OPS = {
    "fs.read": OpSpec("read_file", "fs_read"),
    "fs.write_overwrite": OpSpec("write_file", "fs_write", fat_args={"mode": "overwrite"}),
    "fs.write_create": OpSpec("create_file", "fs_write", fat_args={"mode": "create"}),
    "fs.write_append": OpSpec("append_to_file", "fs_write", fat_args={"mode": "append"}),
    "fs.delete": OpSpec("delete_file", "fs_organize", fat_args={"action": "delete"}),
    "fs.list": OpSpec("list_directory", "fs_organize", fat_args={"action": "list"}),
    "fs.mkdir": OpSpec("create_directory", "fs_organize", fat_args={"action": "mkdir"}),
    "fs.move": OpSpec("move_file", "fs_organize", fat_args={"action": "move"}),
    "fs.glob": OpSpec("glob_files", "fs_search", fat_args={"in_content": False}),
    "fs.grep": OpSpec("grep_files", "fs_search", fat_args={"in_content": True}),
    "fs.run_tests": OpSpec("run_tests", "run_tests"),
    "fs.bash": OpSpec("bash", "bash"),
}

# ---------- git ----------

GIT_OPS = {
    "git.status": OpSpec("git_status", "git_local", fat_args={"action": "status"}),
    "git.diff": OpSpec("git_diff", "git_local", fat_args={"action": "diff"}),
    "git.log": OpSpec("git_log", "git_local", fat_args={"action": "log"}),
    "git.show": OpSpec("git_show", "git_local", fat_args={"action": "show"}),
    "git.add": OpSpec("git_add", "git_local", fat_args={"action": "add"}),
    "git.reset": OpSpec("git_reset", "git_local", fat_args={"action": "reset"}),
    "git.commit": OpSpec("git_commit", "git_commit", fat_args={"action": "commit"}),
    "git.amend": OpSpec("git_commit_amend", "git_commit", fat_args={"action": "amend"}),
    "git.branch_create": OpSpec("git_branch_create", "git_branch", fat_args={"action": "create"}),
    "git.branch_delete": OpSpec("git_branch_delete", "git_branch", fat_args={"action": "delete"}),
    "git.branch_list": OpSpec("git_branch_list", "git_branch", fat_args={"action": "list"}),
    "git.checkout": OpSpec("git_checkout", "git_branch", fat_args={"action": "checkout"}),
    "git.merge": OpSpec("git_merge", "git_branch", fat_args={"action": "merge"}),
    "git.push": OpSpec("git_push", "git_remote", fat_args={"action": "push"}),
    "git.pull": OpSpec("git_pull", "git_remote", fat_args={"action": "pull"}),
}

# ---------- github ----------

GH_OPS = {
    "gh.pr_create": OpSpec("gh_pr_create", "gh_pr", fat_args={"action": "create"}),
    "gh.pr_view": OpSpec("gh_pr_view", "gh_pr", fat_args={"action": "view"}),
    "gh.pr_list": OpSpec("gh_pr_list", "gh_pr", fat_args={"action": "list"}),
    "gh.pr_merge": OpSpec("gh_pr_merge", "gh_pr", fat_args={"action": "merge"}),
    "gh.pr_close": OpSpec("gh_pr_close", "gh_pr", fat_args={"action": "close"}),
    "gh.pr_comment": OpSpec("gh_pr_comment", "gh_pr_feedback", fat_args={"action": "conversation"}),
    "gh.pr_review_comment": OpSpec(
        "gh_pr_review_comment", "gh_pr_feedback", fat_args={"action": "review_comment"}
    ),
    "gh.pr_review_submit": OpSpec(
        "gh_pr_review_submit", "gh_pr_feedback", fat_args={"action": "submit_review"}
    ),
    "gh.issue_create": OpSpec("gh_issue_create", "gh_issue", fat_args={"action": "create"}),
    "gh.issue_view": OpSpec("gh_issue_view", "gh_issue", fat_args={"action": "view"}),
    "gh.issue_comment": OpSpec("gh_issue_comment", "gh_issue", fat_args={"action": "comment"}),
    "gh.issue_close": OpSpec("gh_issue_close", "gh_issue", fat_args={"action": "close"}),
    "gh.repo_view": OpSpec("gh_repo_view", "gh_meta", fat_args={"action": "repo_view"}),
    "gh.workflow_run": OpSpec("gh_workflow_run", "gh_meta", fat_args={"action": "workflow_run"}),
}

OPERATIONS: dict[str, OpSpec] = {**FS_OPS, **GIT_OPS, **GH_OPS}


def op(name: str) -> OpSpec:
    if name not in OPERATIONS:
        raise KeyError(f"Unknown operation: {name!r}. Known: {sorted(OPERATIONS)}")
    return OPERATIONS[name]


def toolbox_of(op_name: str) -> str:
    """The toolbox that an operation belongs to (e.g. 'git.commit' -> 'git')."""
    return op_name.split(".", 1)[0].replace("fs", "filesystem").replace("gh", "github")
