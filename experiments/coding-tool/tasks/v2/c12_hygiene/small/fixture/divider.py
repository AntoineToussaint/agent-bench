"""Small numeric helpers — pre-hygiene."""

from __future__ import annotations


def divide(a, b):
    return a / b


def safe_divide_all(numbers, denom):
    return [divide(n, denom) for n in numbers]


def average(values):
    return divide(sum(values), len(values))
