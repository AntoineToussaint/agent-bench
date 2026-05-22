"""Small numerical statistics utilities.

Every public function shares the same 3-line preamble that validates the
input and coerces it to a list of floats. That repetition is a deliberate
extract-method candidate.
"""

from __future__ import annotations


def mean(values):
    if not values:
        raise ValueError("values must not be empty")
    nums = [float(v) for v in values]
    return sum(nums) / len(nums)


def median(values):
    if not values:
        raise ValueError("values must not be empty")
    nums = [float(v) for v in values]
    nums.sort()
    n = len(nums)
    mid = n // 2
    if n % 2 == 1:
        return nums[mid]
    return (nums[mid - 1] + nums[mid]) / 2.0


def range_(values):
    if not values:
        raise ValueError("values must not be empty")
    nums = [float(v) for v in values]
    return max(nums) - min(nums)
