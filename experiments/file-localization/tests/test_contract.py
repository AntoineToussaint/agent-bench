"""Smoke tests for the file-localization contract (no network, no LLM)."""

from __future__ import annotations

from file_localization.contract import LocalizationTask, score
from file_localization.llm_trial import parse_file_list
from file_localization.swebench_adapter import files_in_patch, to_localization_task
from file_localization.data import Task as RawTask


# --- scoring ---


def test_perfect_recall_passes() -> None:
    s = score(["a.py", "b.py"], frozenset({"a.py", "b.py"}))
    assert s.passed
    assert s.recall == 1.0
    assert s.precision == 1.0
    assert s.f1 == 1.0
    assert s.n_false_positives == 0
    assert s.composite == 1.0


def test_partial_recall_fails_pass_but_records_metric() -> None:
    s = score(["a.py"], frozenset({"a.py", "b.py"}))
    assert not s.passed
    assert s.recall == 0.5
    assert s.precision == 1.0
    assert s.n_false_positives == 0


def test_false_positives_penalize_composite() -> None:
    # found all 2 gold + 2 spurious = recall 1.0, fp=2, gold=2 → composite = 1.0 - 0.05*1.0 = 0.95
    s = score(["a.py", "b.py", "x.py", "y.py"], frozenset({"a.py", "b.py"}), fp_penalty=0.05)
    assert s.passed
    assert s.recall == 1.0
    assert s.precision == 0.5
    assert abs(s.composite - 0.95) < 1e-6


def test_top_k_clipping() -> None:
    # gold has 2 files; we predict 5; with k=1 only the first counts
    s = score(["x.py", "a.py", "b.py", "y.py", "z.py"], frozenset({"a.py", "b.py"}), k=1)
    assert s.recall == 0.0
    assert s.precision == 0.0
    assert s.n_predicted == 1


def test_path_normalization() -> None:
    s = score(["./src/a.py", "src\\b.py"], frozenset({"src/a.py", "src/b.py"}))
    assert s.passed
    assert s.recall == 1.0


# --- parse_file_list ---


def test_parse_file_list_basic() -> None:
    text = """\
Looking at the issue:
FILE: src/foo.py
FILE: tests/test_foo.py

Some commentary.
FILE: src/bar.py
"""
    assert parse_file_list(text) == ["src/foo.py", "tests/test_foo.py", "src/bar.py"]


def test_parse_file_list_dedupes() -> None:
    text = "FILE: a.py\nFILE: a.py\nFILE: b.py"
    assert parse_file_list(text) == ["a.py", "b.py"]


def test_parse_file_list_empty() -> None:
    assert parse_file_list("") == []
    assert parse_file_list("no FILE lines here") == []


# --- swebench adapter ---


def test_files_in_patch_extracts_paths() -> None:
    patch = """\
diff --git a/src/foo.py b/src/foo.py
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,1 +1,1 @@
-x = 1
+x = 2
diff --git a/tests/test_foo.py b/tests/test_foo.py
--- a/tests/test_foo.py
+++ b/tests/test_foo.py
@@ -1,1 +1,1 @@
-assert 1
+assert 2
"""
    assert files_in_patch(patch) == frozenset({"src/foo.py", "tests/test_foo.py"})


def test_files_in_patch_empty() -> None:
    assert files_in_patch("") == frozenset()


def test_swebench_adapter_smoke() -> None:
    raw = RawTask(
        instance_id="test__test-1",
        repo="test/test",
        base_commit="abc123",
        problem_statement="bug in foo",
        patch="diff --git a/src/foo.py b/src/foo.py\n",
        test_patch="diff --git a/tests/test_foo.py b/tests/test_foo.py\n",
    )
    task = to_localization_task(raw)
    assert isinstance(task, LocalizationTask)
    assert task.gold_edit_files == frozenset({"src/foo.py"})
    assert task.gold_test_files == frozenset({"tests/test_foo.py"})
    # gold_all = source files only (localization scores against source,
    # not tests — see contract.py docstring on `gold_all`).
    assert task.gold_all == frozenset({"src/foo.py"})
    assert task.task_id == "test__test-1"
