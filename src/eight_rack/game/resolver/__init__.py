"""Resolver package — backward-compatible re-exports.

All existing imports continue to work:
    from .resolver import Resolver
    from .resolver import FETCH_TARGETS, BASIC_TYPE_LANDS, _effective_power, ...
"""

from .core import Resolver
from .helpers import (
    BASIC_TYPE_LANDS,
    DUAL_LAND_COLORS,
    FETCH_TARGETS,
    MODAL_SPELLS,
    TARGETED_REMOVAL,
    _effective_power,
    _effective_toughness,
    _is_creature,
    destroy_all_creatures,
    scry,
)

__all__ = [
    "Resolver",
    "BASIC_TYPE_LANDS",
    "DUAL_LAND_COLORS",
    "FETCH_TARGETS",
    "MODAL_SPELLS",
    "TARGETED_REMOVAL",
    "_effective_power",
    "_effective_toughness",
    "destroy_all_creatures",
    "scry",
]
