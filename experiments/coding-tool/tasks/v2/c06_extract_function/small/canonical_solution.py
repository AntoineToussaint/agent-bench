"""Canonical solution for c06_extract_function / small."""

from __future__ import annotations

from pathlib import Path


NEW_SOURCE = '''"""Small numerical statistics utilities.

Every public function shares the same 3-line preamble that validates the
input and coerces it to a list of floats. That repetition is a deliberate
extract-method candidate.
"""

from __future__ import annotations


def _validate_and_coerce(values) -> list[float]:
    if not values:
        raise ValueError("values must not be empty")
    return [float(v) for v in values]


def mean(values):
    nums = _validate_and_coerce(values)
    return sum(nums) / len(nums)


def median(values):
    nums = _validate_and_coerce(values)
    nums.sort()
    n = len(nums)
    mid = n // 2
    if n % 2 == 1:
        return nums[mid]
    return (nums[mid - 1] + nums[mid]) / 2.0


def range_(values):
    nums = _validate_and_coerce(values)
    return max(nums) - min(nums)
'''


def apply(workdir: Path) -> None:
    (workdir / "stats.py").write_text(NEW_SOURCE, encoding="utf-8")
