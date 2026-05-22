"""USD budget tracking for sweeps."""

from __future__ import annotations

import threading
from dataclasses import dataclass


class BudgetExceeded(Exception):
    """Raised when adding to a budget would exceed the cap."""


@dataclass
class Budget:
    """Thread-safe cumulative USD cost tracker with optional hard cap.

    Usage:
        budget = Budget(cap_usd=10.0)
        budget.add(0.42)        # ok
        budget.add(...)         # raises BudgetExceeded when cap is hit
        print(budget.spent_usd)
    """

    cap_usd: float | None = None
    spent_usd: float = 0.0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    def add(self, amount_usd: float) -> None:
        with self._lock:
            new_total = self.spent_usd + amount_usd
            if self.cap_usd is not None and new_total > self.cap_usd:
                raise BudgetExceeded(
                    f"adding ${amount_usd:.4f} would exceed cap "
                    f"(spent=${self.spent_usd:.4f}, cap=${self.cap_usd:.4f})"
                )
            self.spent_usd = new_total

    def remaining(self) -> float | None:
        if self.cap_usd is None:
            return None
        return max(0.0, self.cap_usd - self.spent_usd)
