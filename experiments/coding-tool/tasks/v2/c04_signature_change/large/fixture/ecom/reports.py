"""Aggregate reports over collections of orders.

Pure functions: no IO, no mutation. All inputs are iterables of `Order`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

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
    out: dict[int, float] = defaultdict(float)
    for order in orders:
        if not _is_billable(order):
            continue
        out[order.user.user_id] += compute_total(order)
    return {uid: round(total, 2) for uid, total in out.items()}


def status_breakdown(orders: Iterable[Order]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for order in orders:
        counts[order.status] += 1
    return dict(counts)


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
