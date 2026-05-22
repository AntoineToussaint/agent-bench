"""Age classification helpers.

`LEGAL_AGE` is the threshold for adulthood. The predicates below classify
ages into adult / senior / minor buckets.
"""

LEGAL_AGE = 18


def is_adult(age):
    return age > LEGAL_AGE


def is_senior(age):
    return age >= 65


def is_minor(age):
    return age < LEGAL_AGE
