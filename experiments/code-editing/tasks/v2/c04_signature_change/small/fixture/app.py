from billing import compute_total


def checkout(cart):
    return compute_total(cart, discount=0.05)


def quick_total(cart):
    return compute_total(cart)   # no discount
