"""Canonical solution for c11_type_changes / medium."""

from __future__ import annotations

from pathlib import Path


CONTENT = '''"""In-memory repository layer."""

from __future__ import annotations

from typing import Optional

from ecom.models import Order, Product, User


class Repository:
    def __init__(self) -> None:
        self.users: dict[int, User] = {}
        self.products: dict[int, Product] = {}
        self.orders: dict[int, Order] = {}

    def get_user(self, user_id: int) -> Optional[User]:
        return self.users.get(user_id)

    def get_product(self, product_id: int) -> Optional[Product]:
        return self.products.get(product_id)

    def get_order(self, order_id: int) -> Optional[Order]:
        return self.orders.get(order_id)

    def save_order(self, order: Order) -> None:
        self.orders[order.order_id] = order

    def delete_order(self, order_id: int) -> bool:
        return self.orders.pop(order_id, None) is not None


repo = Repository()
'''


def apply(workdir: Path) -> None:
    p = workdir / "ecom" / "repository.py"
    p.write_text(CONTENT, encoding="utf-8")
