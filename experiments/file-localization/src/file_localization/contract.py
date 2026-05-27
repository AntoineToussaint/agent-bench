"""The Task / Result / scoring contract for file-localization trials.

Input (LocalizationTask):
  - The GitHub issue text
  - The repository identifier + base commit
  - Ground truth: which files the gold patch modifies (edit + test)
  - Optional: a pre-computed file listing at base_commit (so the retriever
    has a candidate set without re-cloning)

Output (LocalizationResult):
  - A ranked list of predicted files, most-likely first
  - Optional reasoning text

Scoring:
  - Strict pass:  did the prediction set CONTAIN every gold file?
  - Recall:       fraction of gold files we found
  - Precision:    fraction of predictions that were gold
  - F1:           harmonic mean
  - Composite:    recall − penalty · false_positives (penalizes spam)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


TaskClass = Literal["bug_fix", "feature", "refactor", "performance", "unknown"]


def _norm(p: str) -> str:
    """Normalize a file path for comparison (forward slashes, no leading `./`)."""
    return p.replace("\\", "/").lstrip("./")


def is_test_file(path: str) -> bool:
    """Heuristic: does this path point at a test file?

    Localization is about identifying SOURCE files (where the bug lives).
    Test files are a different problem: the human contributor's PR may
    update tests as a byproduct of the fix (e.g. checksum constants that
    change when behavior changes), which the model can't predict without
    running the test suite. We ignore them in scoring.

    Conventions matched: `tests/`, `test/` directories anywhere in the
    path; files starting with `test_` or ending with `_test.py`.
    """
    n = _norm(path).lower()
    parts = n.split("/")
    if "tests" in parts or "test" in parts:
        return True
    base = parts[-1] if parts else ""
    return base.startswith("test_") or base.endswith("_test.py")


@dataclass(frozen=True)
class LocalizationTask:
    """Input contract: everything a localization trial receives."""

    instance_id: str          # e.g. "django__django-12345"
    issue_text: str           # the GitHub issue / problem statement
    repo: str                 # e.g. "django/django"
    base_commit: str          # commit SHA the issue is against
    gold_edit_files: frozenset[str]    # files the gold patch modifies
    gold_test_files: frozenset[str]    # files the gold test patch modifies
    # Optional: pre-computed file listing at base_commit. None means
    # the trial must fetch it itself (e.g. via local checkout or API).
    repo_file_list: tuple[str, ...] | None = None
    # What KIND of work the issue describes. Trials use this to pick a
    # prompt template — bug-fix prompts mention tracebacks/repros; feature
    # prompts mention "where to ADD code"; etc. SWE-Bench tasks default to
    # "bug_fix" via the adapter.
    task_class: TaskClass = "bug_fix"

    @property
    def task_id(self) -> str:
        return self.instance_id

    @property
    def gold_all(self) -> frozenset[str]:
        """The set scored against. Localization scores source files only.

        Test files (gold_test_files) are kept on the task for reference
        but excluded from scoring because:
          (a) Some test patches are byproduct updates (e.g. CHECKSUM
              constants that change when behavior changes) that the model
              can't predict without running the suite.
          (b) The localization question is "where does the bug live?";
              test placement is a separate concern.
        """
        return self.gold_edit_files


@dataclass
class LocalizationResult:
    """Output contract: what every localization trial must produce."""

    predicted_files: list[str]   # ranked, highest-confidence first
    reasoning: str = ""          # optional natural-language explanation


@dataclass
class LocalizationScore:
    """Computed metrics for one trial."""

    recall: float           # |predicted ∩ gold| / |gold|
    precision: float        # |predicted ∩ gold| / |predicted|
    f1: float
    passed: bool            # recall == 1.0 (all gold files found)
    n_predicted: int
    n_false_positives: int
    composite: float        # recall − fp_penalty · normalized_false_positives

    def as_extra(self) -> dict[str, float | int | bool]:
        """Render as the `extra` dict on a RunRecord."""
        return {
            "recall": self.recall,
            "precision": self.precision,
            "f1": self.f1,
            "n_predicted": self.n_predicted,
            "n_false_positives": self.n_false_positives,
            "composite": self.composite,
        }


def score(
    predicted: list[str],
    gold: frozenset[str] | set[str],
    *,
    k: int | None = None,
    fp_penalty: float = 0.05,
    ignore_test_files: bool = True,
) -> LocalizationScore:
    """Score a ranked list of predictions against gold.

    Args:
        predicted: ranked predictions
        gold: set of gold file paths
        k: if set, only consider the top-k predictions
        fp_penalty: per-false-positive penalty in the composite score,
            applied as `composite = recall - fp_penalty · (fp / max(1, |gold|))`.
        ignore_test_files: if True (default), filter test files out of
            BOTH `gold` and `predicted` before scoring. Localization is
            scored on source files; test files are tolerated in the
            model's output but neither rewarded nor penalized.

    A retriever that finds all gold + N spurious files gets a score in
    [0, 1]; a retriever that misses gold gets less.
    """
    if k is not None:
        predicted = predicted[:k]
    if ignore_test_files:
        predicted = [p for p in predicted if not is_test_file(p)]
        gold = {g for g in gold if not is_test_file(g)}
    pred_n = [_norm(p) for p in predicted]
    gold_n = {_norm(g) for g in gold}

    pred_set = set(pred_n)
    hits = pred_set & gold_n
    tp = len(hits)
    fp = len(pred_set) - tp
    fn = len(gold_n) - tp

    recall = tp / max(1, len(gold_n))
    precision = tp / max(1, len(pred_set)) if pred_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    passed = tp == len(gold_n)
    composite = max(0.0, recall - fp_penalty * (fp / max(1, len(gold_n))))

    return LocalizationScore(
        recall=recall,
        precision=precision,
        f1=f1,
        passed=passed,
        n_predicted=len(predicted),
        n_false_positives=fp,
        composite=composite,
    )
