"""Canonical solution for c04_signature_change / large."""

from __future__ import annotations

from pathlib import Path


PRICING_NEW = '''"""Pricing calculations.

Intentional shape:
  - `apply_tax`, `apply_discount`, `apply_shipping` all follow a similar
    "compute adjustment as a percentage" pattern (extract-method candidate).
  - `TAX_RATE` constant is referenced from multiple places (multi-site candidate).
  - `compute_total` is the orchestrator that all callers go through.
"""

from __future__ import annotations

from ecom.models import Order

TAX_RATE = 0.08
SHIPPING_PER_KG = 2.50
FREE_SHIPPING_THRESHOLD = 100.0
MAX_DISCOUNT_PCT = 50.0


def apply_discount(subtotal: float, discount_pct: float) -> float:
    if discount_pct < 0 or discount_pct > MAX_DISCOUNT_PCT:
        raise ValueError(f"discount_pct out of range: {discount_pct}")
    adjustment = subtotal * (discount_pct / 100.0)
    return subtotal - adjustment


def apply_tax(subtotal: float) -> float:
    adjustment = subtotal * TAX_RATE
    return subtotal + adjustment


def apply_shipping(subtotal: float, weight_kg: float) -> float:
    if subtotal >= FREE_SHIPPING_THRESHOLD:
        return subtotal
    adjustment = weight_kg * SHIPPING_PER_KG
    return subtotal + adjustment


def compute_total(order: Order, currency: str = "USD") -> float:
    # `currency` is accepted for downstream bookkeeping; it does not change
    # how the math is performed.
    del currency
    subtotal = order.subtotal
    after_discount = apply_discount(subtotal, order.discount_pct)
    after_tax = apply_tax(after_discount)
    after_shipping = apply_shipping(after_tax, order.total_weight_kg)
    return round(after_shipping, 2)


def estimate_savings(order: Order) -> float:
    """How much does the customer save vs no-discount."""
    no_disc = apply_shipping(apply_tax(order.subtotal), order.total_weight_kg)
    return round(no_disc - compute_total(order), 2)
'''


ORDERS_NEW = '''"""Order operations."""

from __future__ import annotations

from ecom import inventory
from ecom.models import Order, OrderLine
from ecom.notifications import (
    send_cancellation,
    send_order_confirmation,
    send_shipping_update,
)
from ecom.pricing import compute_total
from ecom.repository import repo


DEFAULT_STOCK_BUFFER = 100


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
        inventory.reserve(line.product.product_id, line.quantity)
    repo.save_order(order)
    total = compute_total(order, currency="EUR")
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
        except inventory.InventoryError:
            # already released or never reserved — don't block cancellation
            pass
    order.status = "cancelled"
    send_cancellation(order)


def add_line(order_id: int, line: OrderLine) -> float:
    order = repo.get_order(order_id)
    order.lines.append(line)
    return compute_total(order)
'''


def apply(workdir: Path) -> None:
    (workdir / "ecom" / "pricing.py").write_text(PRICING_NEW, encoding="utf-8")
    (workdir / "ecom" / "orders.py").write_text(ORDERS_NEW, encoding="utf-8")
