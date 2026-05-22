"""In-memory repository layer."""

from __future__ import annotations

from ecom.models import Order, Product, User


class Repository:
    def __init__(self) -> None:
        self.users: dict[int, User] = {}
        self.products: dict[int, Product] = {}
        self.orders: dict[int, Order] = {}

    def get_user(self, user_id: int) -> User:
        return self.users[user_id]

    def get_product(self, product_id: int) -> Product:
        return self.products[product_id]

    def get_order(self, order_id: int) -> Order:
        return self.orders[order_id]

    def save_order(self, order: Order) -> None:
        self.orders[order.order_id] = order

    def delete_order(self, order_id: int) -> None:
        del self.orders[order_id]


repo = Repository()
