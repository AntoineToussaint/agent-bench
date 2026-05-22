"""Thin "router" layer — looks like a web app but doesn't actually serve HTTP.

Each `route_*` function plays the role of a Flask/FastAPI handler.
"""

from __future__ import annotations

from ecom.models import Order, OrderLine, Product, User
from ecom.orders import add_line, cancel_order, create_order, ship_order
from ecom.pricing import compute_total, estimate_savings
from ecom.repository import repo


def route_create_order(user_id: int, lines: list[OrderLine]) -> dict:
    user = repo.get_user(user_id)
    order = Order(order_id=len(repo.orders) + 1, user=user, lines=lines)
    total = create_order(order)
    return {"order_id": order.order_id, "total": total}


def route_ship_order(order_id: int) -> dict:
    ship_order(order_id)
    return {"order_id": order_id, "status": "shipped"}


def route_cancel_order(order_id: int) -> dict:
    cancel_order(order_id)
    return {"order_id": order_id, "status": "cancelled"}


def route_quote(order_id: int) -> dict:
    order = repo.get_order(order_id)
    return {
        "order_id": order_id,
        "total": compute_total(order),
        "savings": estimate_savings(order),
    }


def route_add_line(order_id: int, product_id: int, quantity: int) -> dict:
    product = repo.get_product(product_id)
    new_total = add_line(order_id, OrderLine(product=product, quantity=quantity))
    return {"order_id": order_id, "total": new_total}
