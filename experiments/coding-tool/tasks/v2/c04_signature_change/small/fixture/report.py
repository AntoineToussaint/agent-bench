from billing import compute_total


def daily(orders):
    return sum(compute_total(o) for o in orders)
