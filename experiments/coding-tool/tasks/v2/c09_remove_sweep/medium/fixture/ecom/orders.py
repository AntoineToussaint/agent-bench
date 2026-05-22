"""Order operations."""

from __future__ import annotations

from ecom.models import Order, OrderLine
from ecom.notifications import (
    send_cancellation,
    send_order_confirmation,
    send_shipping_update,
)
from ecom.pricing import compute_total
from ecom.repository import repo


def create_order(order: Order) -> float:
    repo.save_order(order)
    total = compute_total(order)
    order.notes.append(f"total={total}")
    send_order_confirmation(order)
    return total


def ship_order(order_id: int) -> None:
    order = repo.get_order(order_id)
    order.status = "shipped"
    send_shipping_update(order)


def cancel_order(order_id: int) -> None:
    order = repo.get_order(order_id)
    order.status = "cancelled"
    send_cancellation(order)


def add_line(order_id: int, line: OrderLine) -> float:
    order = repo.get_order(order_id)
    order.lines.append(line)
    return compute_total(order)
