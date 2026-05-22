"""Canonical solution for c12_hygiene / medium."""

from __future__ import annotations

from pathlib import Path


NEW_ORDERS = '''"""Order operations."""

from __future__ import annotations

import logging

from ecom.models import Order, OrderLine
from ecom.notifications import (
    send_cancellation,
    send_order_confirmation,
    send_shipping_update,
)
from ecom.pricing import compute_total
from ecom.repository import repo


logger = logging.getLogger(__name__)


class OrderNotFoundError(Exception):
    pass


def create_order(order: Order) -> float:
    repo.save_order(order)
    total = compute_total(order)
    order.notes.append(f"total={total}")
    send_order_confirmation(order)
    return total


def ship_order(order_id: int) -> None:
    try:
        order = repo.get_order(order_id)
    except KeyError as exc:
        logger.exception(f"order {order_id} not found")
        raise OrderNotFoundError(f"order {order_id} not found") from exc
    order.status = "shipped"
    send_shipping_update(order)


def cancel_order(order_id: int) -> None:
    try:
        order = repo.get_order(order_id)
    except KeyError as exc:
        logger.exception(f"order {order_id} not found")
        raise OrderNotFoundError(f"order {order_id} not found") from exc
    order.status = "cancelled"
    send_cancellation(order)


def add_line(order_id: int, line: OrderLine) -> float:
    try:
        order = repo.get_order(order_id)
    except KeyError as exc:
        logger.exception(f"order {order_id} not found")
        raise OrderNotFoundError(f"order {order_id} not found") from exc
    order.lines.append(line)
    return compute_total(order)
'''


def apply(workdir: Path) -> None:
    (workdir / "ecom" / "orders.py").write_text(NEW_ORDERS, encoding="utf-8")
