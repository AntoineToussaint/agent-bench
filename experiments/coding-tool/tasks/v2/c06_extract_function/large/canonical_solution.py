"""Canonical solution for c06_extract_function / large."""

from __future__ import annotations

from pathlib import Path


NEW_NOTIFICATIONS = '''"""Customer notifications.

Intentional shape: three near-identical handlers (`send_order_confirmation`,
`send_shipping_update`, `send_cancellation`). Naive find-and-replace can't
target one of them without disambiguation context — they share the same
boilerplate.
"""

from __future__ import annotations

from ecom.models import Order


SUPPORT_EMAIL = "support@example.com"


def _build_payload(order: Order, subject_template: str, body_template: str) -> dict:
    return {
        "to": order.user.email,
        "subject": subject_template.format(order_id=order.order_id),
        "body": body_template.format(name=order.user.name),
        "reply_to": SUPPORT_EMAIL,
    }


def send_order_confirmation(order: Order) -> dict:
    print(f"sending order confirmation to {order.user.email}")
    return _build_payload(
        order,
        "Order #{order_id} confirmed",
        "Thanks {name}, your order is on its way.",
    )


def send_shipping_update(order: Order) -> dict:
    print(f"sending shipping update to {order.user.email}")
    return _build_payload(
        order,
        "Order #{order_id} shipped",
        "Hi {name}, your order is on the way.",
    )


def send_cancellation(order: Order) -> dict:
    print(f"sending cancellation to {order.user.email}")
    return _build_payload(
        order,
        "Order #{order_id} cancelled",
        "Hi {name}, your order has been cancelled.",
    )
'''


NEW_REPORTS = '''"""Aggregate reports over collections of orders.

Pure functions: no IO, no mutation. All inputs are iterables of `Order`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable, Optional

from ecom.models import Order
from ecom.pricing import compute_total


@dataclass
class DailySales:
    on_date: date
    order_count: int
    gross_revenue: float
    average_order_value: float


@dataclass
class ProductRanking:
    product_id: int
    name: str
    units_sold: int
    revenue: float


def _order_date(order: Order) -> Optional[date]:
    """Pull a date out of an order's notes if present, else None.

    Orders are dated by an optional `placed_on=YYYY-MM-DD` note. Orders without
    a placed_on note are treated as undated and excluded from date filters.
    """
    for note in order.notes:
        if note.startswith("placed_on="):
            raw = note.split("=", 1)[1]
            try:
                return datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError:
                continue
    return None


def _is_billable(order: Order) -> bool:
    return order.status != "cancelled"


def _group_by_sum(items, key_fn: Callable, value_fn: Callable) -> dict:
    out: dict = defaultdict(lambda: 0)
    for item in items:
        out[key_fn(item)] += value_fn(item)
    return dict(out)


def daily_sales(orders: Iterable[Order], on_date: date) -> DailySales:
    matching = [
        o for o in orders if _is_billable(o) and _order_date(o) == on_date
    ]
    gross = round(sum(compute_total(o) for o in matching), 2)
    count = len(matching)
    aov = round(gross / count, 2) if count else 0.0
    return DailySales(
        on_date=on_date,
        order_count=count,
        gross_revenue=gross,
        average_order_value=aov,
    )


def top_products(orders: Iterable[Order], n: int = 5) -> list[ProductRanking]:
    if n <= 0:
        return []
    units: dict[int, int] = defaultdict(int)
    revenue: dict[int, float] = defaultdict(float)
    names: dict[int, str] = {}
    for order in orders:
        if not _is_billable(order):
            continue
        for line in order.lines:
            pid = line.product.product_id
            units[pid] += line.quantity
            revenue[pid] += line.line_total
            names[pid] = line.product.name
    rankings = [
        ProductRanking(
            product_id=pid,
            name=names[pid],
            units_sold=units[pid],
            revenue=round(revenue[pid], 2),
        )
        for pid in units
    ]
    rankings.sort(key=lambda r: (-r.units_sold, -r.revenue, r.product_id))
    return rankings[:n]


def revenue_by_user(orders: Iterable[Order]) -> dict[int, float]:
    billable = [o for o in orders if _is_billable(o)]
    totals = _group_by_sum(
        billable,
        key_fn=lambda o: o.user.user_id,
        value_fn=lambda o: compute_total(o),
    )
    return {uid: round(total, 2) for uid, total in totals.items()}


def status_breakdown(orders: Iterable[Order]) -> dict[str, int]:
    return _group_by_sum(orders, key_fn=lambda o: o.status, value_fn=lambda o: 1)


def average_order_value(orders: Iterable[Order]) -> float:
    billable = [o for o in orders if _is_billable(o)]
    if not billable:
        return 0.0
    total = sum(compute_total(o) for o in billable)
    return round(total / len(billable), 2)


def total_units_sold(orders: Iterable[Order]) -> int:
    return sum(
        line.quantity
        for order in orders
        if _is_billable(order)
        for line in order.lines
    )


def revenue_in_range(
    orders: Iterable[Order],
    start: date,
    end: date,
) -> float:
    if end < start:
        raise ValueError("end date precedes start date")
    total = 0.0
    for order in orders:
        if not _is_billable(order):
            continue
        placed = _order_date(order)
        if placed is None:
            continue
        if start <= placed <= end:
            total += compute_total(order)
    return round(total, 2)


def biggest_spender(orders: Iterable[Order]) -> Optional[int]:
    revenue = revenue_by_user(orders)
    if not revenue:
        return None
    return max(revenue, key=lambda uid: revenue[uid])
'''


def apply(workdir: Path) -> None:
    (workdir / "ecom" / "notifications.py").write_text(
        NEW_NOTIFICATIONS, encoding="utf-8"
    )
    (workdir / "ecom" / "reports.py").write_text(NEW_REPORTS, encoding="utf-8")
