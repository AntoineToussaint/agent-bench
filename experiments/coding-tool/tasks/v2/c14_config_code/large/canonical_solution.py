"""Canonical solution for c14_config_code / large."""

from __future__ import annotations

from pathlib import Path


CONFIG_PY = '''"""Centralized configuration constants for the ecom package."""

from __future__ import annotations


TAX_RATE = 0.08
SHIPPING_PER_KG = 2.50
FREE_SHIPPING_THRESHOLD = 100.0
MAX_DISCOUNT_PCT = 50.0
SUPPORT_EMAIL = "support@example.com"
LOW_STOCK_DEFAULT_THRESHOLD = 5
'''


NEW_PRICING_PY = '''"""Pricing calculations.

Intentional shape:
  - `apply_tax`, `apply_discount`, `apply_shipping` all follow a similar
    "compute adjustment as a percentage" pattern (extract-method candidate).
  - `TAX_RATE` constant is referenced from multiple places (multi-site candidate).
  - `compute_total` is the orchestrator that all callers go through.
"""

from __future__ import annotations

from ecom.config import (
    FREE_SHIPPING_THRESHOLD,
    MAX_DISCOUNT_PCT,
    SHIPPING_PER_KG,
    TAX_RATE,
)
from ecom.models import Order


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


def compute_total(order: Order) -> float:
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


NEW_NOTIFICATIONS_PY = '''"""Customer notifications.

Intentional shape: three near-identical handlers (`send_order_confirmation`,
`send_shipping_update`, `send_cancellation`). Naive find-and-replace can't
target one of them without disambiguation context — they share the same
boilerplate.
"""

from __future__ import annotations

from ecom.config import SUPPORT_EMAIL
from ecom.models import Order


def send_order_confirmation(order: Order) -> dict:
    print(f"sending order confirmation to {order.user.email}")
    return {
        "to": order.user.email,
        "subject": f"Order #{order.order_id} confirmed",
        "body": f"Thanks {order.user.name}, your order is on its way.",
        "reply_to": SUPPORT_EMAIL,
    }


def send_shipping_update(order: Order) -> dict:
    print(f"sending shipping update to {order.user.email}")
    return {
        "to": order.user.email,
        "subject": f"Order #{order.order_id} shipped",
        "body": f"Hi {order.user.name}, your order is on the way.",
        "reply_to": SUPPORT_EMAIL,
    }


def send_cancellation(order: Order) -> dict:
    print(f"sending cancellation to {order.user.email}")
    return {
        "to": order.user.email,
        "subject": f"Order #{order.order_id} cancelled",
        "body": f"Hi {order.user.name}, your order has been cancelled.",
        "reply_to": SUPPORT_EMAIL,
    }
'''


NEW_INVENTORY_PY = '''"""In-memory inventory tracking and reservation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ecom.config import LOW_STOCK_DEFAULT_THRESHOLD


class InventoryError(Exception):
    pass


@dataclass
class Stock:
    product_id: int
    on_hand: int = 0
    reserved: int = 0
    reorder_threshold: int = 5
    notes: list[str] = field(default_factory=list)

    @property
    def available(self) -> int:
        return max(self.on_hand - self.reserved, 0)

    @property
    def is_low(self) -> bool:
        return self.available <= self.reorder_threshold


_stock: dict[int, Stock] = {}


def register_stock(stock: Stock) -> None:
    _stock[stock.product_id] = stock


def get_stock(product_id: int) -> Stock:
    if product_id not in _stock:
        raise InventoryError(f"no stock record for product {product_id}")
    return _stock[product_id]


def ensure_stock(product_id: int, on_hand: int = 0, reorder_threshold: int = 5) -> Stock:
    if product_id in _stock:
        return _stock[product_id]
    stock = Stock(
        product_id=product_id,
        on_hand=on_hand,
        reorder_threshold=reorder_threshold,
    )
    _stock[product_id] = stock
    return stock


def restock(product_id: int, qty: int) -> Stock:
    if qty <= 0:
        raise InventoryError(f"restock qty must be positive, got {qty}")
    stock = ensure_stock(product_id)
    stock.on_hand += qty
    stock.notes.append(f"restock+{qty}")
    return stock


def reserve(product_id: int, qty: int) -> Stock:
    if qty <= 0:
        raise InventoryError(f"reserve qty must be positive, got {qty}")
    stock = ensure_stock(product_id)
    if stock.available < qty:
        raise InventoryError(
            f"insufficient stock for product {product_id}: "
            f"requested {qty}, available {stock.available}"
        )
    stock.reserved += qty
    stock.notes.append(f"reserve+{qty}")
    return stock


def release(product_id: int, qty: int) -> Stock:
    if qty <= 0:
        raise InventoryError(f"release qty must be positive, got {qty}")
    stock = ensure_stock(product_id)
    if stock.reserved < qty:
        raise InventoryError(
            f"cannot release {qty} for product {product_id}: "
            f"only {stock.reserved} reserved"
        )
    stock.reserved -= qty
    stock.notes.append(f"release+{qty}")
    return stock


def fulfill(product_id: int, qty: int) -> Stock:
    """Consume reserved stock when an order ships."""
    if qty <= 0:
        raise InventoryError(f"fulfill qty must be positive, got {qty}")
    stock = ensure_stock(product_id)
    if stock.reserved < qty:
        raise InventoryError(
            f"cannot fulfill {qty} for product {product_id}: "
            f"only {stock.reserved} reserved"
        )
    if stock.on_hand < qty:
        raise InventoryError(
            f"cannot fulfill {qty} for product {product_id}: "
            f"only {stock.on_hand} on hand"
        )
    stock.reserved -= qty
    stock.on_hand -= qty
    stock.notes.append(f"fulfill+{qty}")
    return stock


def low_stock_alerts(threshold: Optional[int] = LOW_STOCK_DEFAULT_THRESHOLD) -> list[Stock]:
    out: list[Stock] = []
    for stock in _stock.values():
        cutoff = threshold if threshold is not None else stock.reorder_threshold
        if stock.available <= cutoff:
            out.append(stock)
    out.sort(key=lambda s: (s.available, s.product_id))
    return out


def total_available() -> int:
    return sum(s.available for s in _stock.values())


def total_reserved() -> int:
    return sum(s.reserved for s in _stock.values())


def clear_stock() -> None:
    _stock.clear()


def snapshot() -> dict[int, dict[str, int]]:
    return {
        pid: {
            "on_hand": s.on_hand,
            "reserved": s.reserved,
            "available": s.available,
        }
        for pid, s in _stock.items()
    }
'''


def apply(workdir: Path) -> None:
    (workdir / "ecom" / "config.py").write_text(CONFIG_PY, encoding="utf-8")
    (workdir / "ecom" / "pricing.py").write_text(NEW_PRICING_PY, encoding="utf-8")
    (workdir / "ecom" / "notifications.py").write_text(NEW_NOTIFICATIONS_PY, encoding="utf-8")
    (workdir / "ecom" / "inventory.py").write_text(NEW_INVENTORY_PY, encoding="utf-8")
