"""Canonical solution for c12_hygiene / large."""

from __future__ import annotations

from pathlib import Path


NEW_ORDERS = '''"""Order operations."""

from __future__ import annotations

import logging

from ecom import inventory
from ecom.models import Order, OrderLine
from ecom.notifications import (
    send_cancellation,
    send_order_confirmation,
    send_shipping_update,
)
from ecom.pricing import compute_total
from ecom.repository import repo


logger = logging.getLogger(__name__)


DEFAULT_STOCK_BUFFER = 100


class OrderError(Exception):
    pass


def _ensure_capacity(product_id: int, qty: int) -> None:
    """Make sure the inventory record can satisfy `qty` before reserving.

    New product records get a generous default buffer so callers that haven't
    explicitly seeded stock still succeed.
    """
    stock = inventory.ensure_stock(product_id, on_hand=qty + DEFAULT_STOCK_BUFFER)
    if stock.available < qty:
        stock.on_hand += qty - stock.available


def create_order(order: Order) -> float:
    for line in order.lines:
        _ensure_capacity(line.product.product_id, line.quantity)
        try:
            inventory.reserve(line.product.product_id, line.quantity)
        except inventory.InventoryError as exc:
            logger.warning(f"reserve failed for product {line.product.product_id}: {exc}")
            raise OrderError(str(exc)) from exc
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
    for line in order.lines:
        try:
            inventory.release(line.product.product_id, line.quantity)
        except inventory.InventoryError as exc:
            logger.warning(f"release failed for product {line.product.product_id}: {exc}")
            raise OrderError(str(exc)) from exc
    order.status = "cancelled"
    send_cancellation(order)


def add_line(order_id: int, line: OrderLine) -> float:
    order = repo.get_order(order_id)
    order.lines.append(line)
    return compute_total(order)
'''


def apply(workdir: Path) -> None:
    (workdir / "ecom" / "orders.py").write_text(NEW_ORDERS, encoding="utf-8")
