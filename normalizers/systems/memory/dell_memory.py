# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell Memory: Oem.Dell fields and PSU-style Assembly manufacture dates in ``Oem.Redpool``."""

from __future__ import annotations

from typing import Any, Dict

from ...optional import omit_if_null
from ...types import NormalizationContext
from .base import BaseMemoryNormalizer, memory_oem
from .memory_location import generate_memory_location
from .dell import (
    apply_prefetched_dell_memory_assembly_manufacture,
    extend_redpool_from_dell_oem,
    locator_to_location,
    prefetch_dell_memory_assembly_manufacture,
)


def _extend(rp: Dict[str, Any], oem: Dict[str, Any], ctx: NormalizationContext) -> None:
    dell = oem.get("Dell")
    if isinstance(dell, dict):
        extend_redpool_from_dell_oem(rp, dell)
    apply_prefetched_dell_memory_assembly_manufacture(rp, ctx)


def _dell_memory_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    return memory_oem(ctx, _extend)


def _dell_memory_location(ctx: NormalizationContext) -> Any:
    return generate_memory_location(ctx, locator=locator_to_location)


def _dell_memory_media(ctx: NormalizationContext) -> list:
    """``MemoryMedia`` from the BMC, else from ``Oem.Dell.DellMemory.MemoryTechnology``.

    iDRAC reports ``"DRAM"`` for every DIMM in the captures. It is the only technology
    mapped; any other value is left out rather than guessed.
    """
    if ctx.data.get("MemoryMedia"):
        return ctx.data["MemoryMedia"]
    dell = (ctx.data.get("Oem") or {}).get("Dell")
    dm = dell.get("DellMemory") if isinstance(dell, dict) else None
    tech = dm.get("MemoryTechnology") if isinstance(dm, dict) else None
    return ["DRAM"] if tech == "DRAM" else []


class DellMemoryNormalizer(BaseMemoryNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_dell_memory_assembly_manufacture(ctx)

    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["Oem"] = _dell_memory_oem
        mapping["MemoryLocation"] = omit_if_null(_dell_memory_location)
        mapping["MemoryMedia"] = _dell_memory_media
        return mapping
