"""Age-bracket helpers."""

from __future__ import annotations


LEGAL_AGE = 18
SENIOR_AGE = 65


def is_adult(age):
    return age >= LEGAL_AGE


def is_senior(age):
    return age >= SENIOR_AGE
