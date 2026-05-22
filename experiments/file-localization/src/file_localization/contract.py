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


def _norm(p: str) -> str:
    """Normalize a file path for comparison (forward slashes, no leading `./`)."""
    return p.replace("\\", "/").lstrip("./")


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

    @property
    def task_id(self) -> str:
        return self.instance_id

    @property
    def gold_all(self) -> frozenset[str]:
        return self.gold_edit_files | self.gold_test_files


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
) -> LocalizationScore:
    """Score a ranked list of predictions against gold.

    Args:
        predicted: ranked predictions
        gold: set of gold file paths
        k: if set, only consider the top-k predictions
        fp_penalty: per-false-positive penalty in the composite score,
            applied as `composite = recall - fp_penalty · (fp / max(1, |gold|))`.
            A retriever that finds all gold + N spurious files gets a
            score in [0, 1]; a retriever that misses gold gets less.
    """
    if k is not None:
        predicted = predicted[:k]
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
