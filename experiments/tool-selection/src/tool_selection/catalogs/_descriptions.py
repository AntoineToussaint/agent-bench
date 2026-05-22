"""Toolbox-level descriptions, shared between narrow and fat catalogs.

These are what the LLM-router and embedding-router approaches see when picking
which toolbox(es) to expand. They're intentionally real-feeling — 3-4 sentences
covering typical use, anchor tools, and when NOT to use.
"""

FILESYSTEM_DESCRIPTION = """\
Read, write, search, and organize files on the local working tree. Use this \
toolbox for inspecting source files, creating or modifying tracked files, \
listing directory contents, and searching across the project with glob or \
grep. Do NOT use it for committing changes (that's git) or for any operation \
that needs to reach a remote (that's github)."""

GIT_DESCRIPTION = """\
Manage the local git repository: stage and commit changes, inspect history \
and diffs, manipulate branches, and interact with remotes via push/pull. Use \
this toolbox for any operation that touches the .git directory or affects \
local repository state. Use it BEFORE github when a workflow involves both \
(commit locally first, then create PR). Do NOT use it for creating pull \
requests, leaving PR comments, or any other GitHub-API-level operation."""

GITHUB_DESCRIPTION = """\
Interact with GitHub at the API level: create and manage pull requests, leave \
PR review comments, file issues, and trigger workflows. Use this toolbox for \
anything that happens on github.com after code has been pushed. Distinguish \
between conversation comments on a PR (general discussion) and inline review \
comments (anchored to a line in the diff). Do NOT use it for local git \
operations like commit or branch creation."""

TOOLBOX_DESCRIPTIONS = {
    "filesystem": FILESYSTEM_DESCRIPTION,
    "git": GIT_DESCRIPTION,
    "github": GITHUB_DESCRIPTION,
}
