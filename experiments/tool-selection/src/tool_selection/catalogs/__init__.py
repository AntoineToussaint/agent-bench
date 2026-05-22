"""Tool catalogs used in the benchmark.

Two granularities of the same capabilities:
- narrow_catalog: ~40 small tools (one per operation, with sibling confusables)
- fat_catalog:    ~12 wide tools (action enum + conditionally-required args)

Both expose the same three toolboxes (filesystem, git, github) with the same
toolbox-level descriptions, so toolbox-routing approaches see an identical
outer surface.
"""

from tool_selection.types import Catalog, Granularity

from .fat import fat_catalog
from .huge import narrow_rich_80_catalog, narrow_rich_150_catalog
from .narrow import narrow_catalog
from .narrow_rich import narrow_rich_catalog
from .primitive import primitive_catalog

CATALOGS: dict[Granularity, Catalog] = {
    "narrow": narrow_catalog,
    "fat": fat_catalog,
    "narrow-rich": narrow_rich_catalog,
    "narrow-rich-80": narrow_rich_80_catalog,
    "narrow-rich-150": narrow_rich_150_catalog,
    "primitive": primitive_catalog,
}


def get_catalog(granularity: Granularity) -> Catalog:
    return CATALOGS[granularity]


__all__ = [
    "narrow_catalog",
    "fat_catalog",
    "narrow_rich_catalog",
    "narrow_rich_80_catalog",
    "narrow_rich_150_catalog",
    "CATALOGS",
    "get_catalog",
]
