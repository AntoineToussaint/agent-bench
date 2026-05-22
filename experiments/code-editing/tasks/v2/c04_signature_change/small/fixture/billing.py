"""Tiny billing helper — toy size."""

from __future__ import annotations


def compute_total(items, discount=0.0):
    subtotal = sum(price for _, price in items)
    return subtotal * (1 - discount)
