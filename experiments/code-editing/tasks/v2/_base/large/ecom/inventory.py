"""In-memory inventory tracking and reservation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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


def low_stock_alerts(threshold: Optional[int] = None) -> list[Stock]:
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
