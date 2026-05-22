from math_utils import deprecated_double, square


def total(values):
    return sum(deprecated_double(v) for v in values)


def squares(values):
    return [square(v) for v in values]
