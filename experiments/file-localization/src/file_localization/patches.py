from __future__ import annotations

import re

from unidiff import PatchSet

# Heuristic for classifying gold-patch files as test files.
# Conservative: matches /tests?/, /testing/, test_*.py, *_test.go, *.test.ts, etc.
TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|testing)(/|$)"
    r"|(^|/)test_[^/]+$"
    r"|_test\.[^/]+$"
    r"|\.test\.[^/]+$"
    r"|(^|/)spec/"
    r"|_spec\.[^/]+$",
    re.IGNORECASE,
)


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH_RE.search(path))


def files_in_patch(patch: str) -> list[str]:
    """Return file paths touched by a unified-diff patch, in patch order."""
    seen: list[str] = []
    for p in PatchSet(patch):
        for raw in (p.target_file, p.source_file):
            if raw and raw != "/dev/null":
                path = re.sub(r"^[ab]/", "", raw)
                if path and path not in seen:
                    seen.append(path)
                break
    return seen


def split_edit_test(paths: list[str]) -> tuple[list[str], list[str]]:
    edits = [p for p in paths if not is_test_path(p)]
    tests = [p for p in paths if is_test_path(p)]
    return edits, tests
