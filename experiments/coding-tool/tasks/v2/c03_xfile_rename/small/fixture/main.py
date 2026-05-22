from utils import helper, triple, quadruple


def compute(a, b):
    return helper(a) + triple(b)


def all_helpers(x):
    return helper(x), triple(x), quadruple(x)
