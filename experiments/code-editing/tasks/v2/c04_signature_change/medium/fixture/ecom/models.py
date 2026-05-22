"""Domain models for the mini e-commerce app."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Address:
    street: str
    city: str
    country: str
    postal_code: str


@dataclass
class User:
    user_id: int
    email: str
    name: str
    address: Optional[Address] = None


@dataclass
class Product:
    product_id: int
    name: str
    unit_price: float
    weight_kg: float = 0.5


@dataclass
class OrderLine:
    product: Product
    quantity: int

    @property
    def line_total(self) -> float:
        return self.product.unit_price * self.quantity


@dataclass
class Order:
    order_id: int
    user: User
    lines: list[OrderLine]
    discount_pct: float = 0.0
    status: str = "pending"
    notes: list[str] = field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return sum(line.line_total for line in self.lines)

    @property
    def total_weight_kg(self) -> float:
        return sum(line.product.weight_kg * line.quantity for line in self.lines)
