"""Argument-value matchers for RequiredCall.args.

A task asserts "the model called git_commit with message containing 'Fix auth bug'"
by using Contains("Fix auth bug") rather than an exact string — otherwise we'd
overfit on phrasing the model can legitimately vary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Matcher(Protocol):
    def matches(self, value: Any) -> bool: ...
    def describe(self) -> str: ...


@dataclass(frozen=True)
class Eq:
    value: Any

    def matches(self, value: Any) -> bool:
        return value == self.value

    def describe(self) -> str:
        return f"== {self.value!r}"


@dataclass(frozen=True)
class Regex:
    pattern: str
    flags: int = re.IGNORECASE

    def matches(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return bool(re.search(self.pattern, value, self.flags))

    def describe(self) -> str:
        return f"matches /{self.pattern}/"


@dataclass(frozen=True)
class Contains:
    """Substring match for strings; substring-in-any-element for lists/tuples
    of strings; element match for lists of other types."""

    needle: Any
    case_insensitive: bool = True

    def matches(self, value: Any) -> bool:
        if isinstance(value, str) and isinstance(self.needle, str):
            if self.case_insensitive:
                return self.needle.lower() in value.lower()
            return self.needle in value
        if isinstance(value, (list, tuple)):
            if isinstance(self.needle, str):
                # Substring-in-any-element for string needles (e.g. "dark.css"
                # in ["src/themes/dark.css"]). Falls back to element equality
                # for non-string elements.
                lo = self.needle.lower() if self.case_insensitive else self.needle
                return any(
                    isinstance(x, str)
                    and (lo in x.lower() if self.case_insensitive else self.needle in x)
                    for x in value
                )
            return self.needle in value
        return False

    def describe(self) -> str:
        return f"contains {self.needle!r}"


@dataclass(frozen=True)
class Present:
    """Just asserts the key was supplied with a non-None value."""

    def matches(self, value: Any) -> bool:
        return value is not None

    def describe(self) -> str:
        return "present"


@dataclass(frozen=True)
class OneOf:
    options: tuple[Any, ...]

    def matches(self, value: Any) -> bool:
        return value in self.options

    def describe(self) -> str:
        return f"in {self.options!r}"


def to_matcher(spec: Any) -> Matcher:
    """Coerce a value into a Matcher. Bare values become Eq; Matchers pass through."""
    if isinstance(spec, Matcher):
        return spec
    return Eq(spec)
