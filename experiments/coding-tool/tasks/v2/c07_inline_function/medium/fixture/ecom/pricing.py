"""Pricing calculations.

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


def _percent(subtotal: float, pct: float) -> float:
    return subtotal * (pct / 100.0)


def apply_discount(subtotal: float, discount_pct: float) -> float:
    if discount_pct < 0 or discount_pct > MAX_DISCOUNT_PCT:
        raise ValueError(f"discount_pct out of range: {discount_pct}")
    adjustment = _percent(subtotal, discount_pct)
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
