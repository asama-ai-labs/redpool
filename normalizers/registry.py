# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Central normalizer registry.

Resource modules register their normalizers here at import time.
The proxy layer looks up normalizers by path pattern (e.g. "Systems/Processors").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .base import ResourceNormalizer
from .types import NormalizationContext
from .vendor_id import canonical_server_vendor


@dataclass
class NormalizerEntry:
    """A complete set of normalizers for a resource type."""

    base: ResourceNormalizer
    vendors: Dict[str, ResourceNormalizer] = field(default_factory=dict)

    def for_vendor(self, vendor: str) -> ResourceNormalizer:
        """The vendor's normalizer, or the base one when the vendor has no override."""
        return self.vendors.get(canonical_server_vendor(vendor), self.base)


class CollectionMapping(dict):  # type: ignore[type-arg]
    """A collection's base mapping, plus per-vendor replacement mappings in ``vendors``."""

    def __init__(self, mapping: Dict[str, Any]) -> None:
        super().__init__(mapping)
        self.vendors: Dict[str, Dict[str, Any]] = {}
        self.prefetches: Dict[str, Callable[[NormalizationContext], None]] = {}

    def for_vendor(self, vendor: str) -> Dict[str, Any]:
        """The vendor's mapping, or the base one when the vendor has no override."""
        return self.vendors.get(canonical_server_vendor(vendor), self)

    def prefetch_for_vendor(
        self, vendor: str
    ) -> Optional[Callable[[NormalizationContext], None]]:
        """The vendor's prefetch for this collection, when it registered one."""
        return self.prefetches.get(canonical_server_vendor(vendor))


_registry: Dict[str, NormalizerEntry] = {}
_collection_registry: Dict[str, CollectionMapping] = {}


def register_base(path_pattern: str, normalizer: ResourceNormalizer) -> None:
    """Register the base (vendor-agnostic) resource normalizer."""
    if path_pattern in _registry:
        _registry[path_pattern].base = normalizer
    else:
        _registry[path_pattern] = NormalizerEntry(base=normalizer)


def register_resource(
    path_pattern: str, vendor: str, normalizer: ResourceNormalizer
) -> None:
    """Register a vendor-specific resource normalizer.

    *vendor* is canonicalized, so "Dell Inc." registers as "Dell".
    """
    if path_pattern not in _registry:
        raise ValueError(
            f"No base normalizer registered for '{path_pattern}'. "
            "Call register_base first."
        )
    key = canonical_server_vendor(vendor)
    existing = _registry[path_pattern].vendors.get(key)
    if existing is not None and type(existing) is not type(normalizer):
        raise ValueError(
            f"'{path_pattern}' already has a {key} normalizer "
            f"({type(existing).__name__}); refusing to replace it with "
            f"{type(normalizer).__name__}."
        )
    _registry[path_pattern].vendors[key] = normalizer


def register_collection(path_pattern: str, mapping: Dict[str, Any]) -> None:
    """Register a collection normalizer (flat mapping dict)."""
    new = CollectionMapping(mapping)
    existing = _collection_registry.get(path_pattern)
    if existing is not None:
        new.vendors = existing.vendors
        new.prefetches = existing.prefetches
    _collection_registry[path_pattern] = new


def register_collection_override(
    path_pattern: str,
    vendor: str,
    mapping: Dict[str, Any],
    prefetch: Optional[Callable[[NormalizationContext], None]] = None,
) -> None:
    """Register the complete mapping a vendor uses for a collection.

    Build it from the base mapping: ``{**COLLECTION_MAPPING, "Members": ...}``.
    *prefetch*, when given, runs before the mapping is evaluated and may write only to
    ``ctx.prefetched``, as a resource normalizer's ``prefetch`` does.
    """
    if path_pattern not in _collection_registry:
        raise ValueError(
            f"No collection mapping registered for '{path_pattern}'. "
            "Call register_collection first."
        )
    entry = _collection_registry[path_pattern]
    entry.vendors[canonical_server_vendor(vendor)] = mapping
    if prefetch is not None:
        entry.prefetches[canonical_server_vendor(vendor)] = prefetch


def get_resource_entry(path_pattern: str) -> Optional[NormalizerEntry]:
    """Look up the full normalizer entry for a resource path pattern."""
    return _registry.get(path_pattern)


def get_collection_mapping(path_pattern: str) -> Optional[CollectionMapping]:
    """Look up the collection mapping for a path pattern."""
    return _collection_registry.get(path_pattern)
