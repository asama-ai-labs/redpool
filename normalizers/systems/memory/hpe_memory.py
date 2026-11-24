# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE Memory: Oem.Hpe manufacturer, DIMMStatus, and ``Oem.Redpool`` fields."""

from __future__ import annotations

from typing import Any, Dict

from ...optional import omit_if_null
from ...types import NormalizationContext
from .base import (
    BaseMemoryNormalizer,
    memory_status,
    memory_manufacturer,
    memory_oem,
)
from .hpe import (
    effective_hpe_memory_manufacturer,
    extend_redpool_from_hpe_oem,
    hpe_bmc_to_canonical_memory_location,
    map_hpe_dimm_status,
)
from .memory_location import generate_memory_location, model_fold


def _hpe_block(ctx: NormalizationContext) -> Any:
    oem = ctx.data.get("Oem") or {}
    hpe = oem.get("Hpe") if isinstance(oem, dict) else None
    return hpe if isinstance(hpe, dict) else None


def _hpe_manufacturer(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Manufacturer")
    hpe = _hpe_block(ctx)
    if hpe is not None:
        raw = effective_hpe_memory_manufacturer(raw, hpe)
    return memory_manufacturer(raw)


def _hpe_status(ctx: NormalizationContext) -> Any:
    out = memory_status(ctx)
    hpe = _hpe_block(ctx)
    if hpe is None:
        return out
    mapped = map_hpe_dimm_status(hpe.get("DIMMStatus"))
    if mapped:
        # Prefer DIMMStatus when Health/State missing or HealthRollup absent/Unknown.
        for key, val in mapped.items():
            cur = out.get(key)
            if cur is None or cur == "" or (key == "HealthRollup" and cur == "Unknown"):
                out[key] = val
        if not out.get("Health"):
            out["Health"] = mapped["Health"]
        if not out.get("State"):
            out["State"] = mapped["State"]
        if not out.get("HealthRollup") or out.get("HealthRollup") == "Unknown":
            out["HealthRollup"] = mapped["HealthRollup"]
    return out


def _extend(rp: Dict[str, Any], oem: Dict[str, Any], ctx: NormalizationContext) -> None:
    hpe = oem.get("Hpe")
    if isinstance(hpe, dict):
        extend_redpool_from_hpe_oem(rp, hpe)


def _hpe_memory_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    return memory_oem(ctx, _extend)


def _canonical_location(ctx: NormalizationContext, quad: Any) -> Any:
    return hpe_bmc_to_canonical_memory_location(model_fold(ctx.model), *quad) or quad


def _hpe_memory_location(ctx: NormalizationContext) -> Any:
    return generate_memory_location(ctx, canonical=_canonical_location)


class HPEMemoryNormalizer(BaseMemoryNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["Manufacturer"] = _hpe_manufacturer
        mapping["Status"] = _hpe_status
        mapping["MemoryLocation"] = omit_if_null(_hpe_memory_location)
        mapping["Oem"] = _hpe_memory_oem
        return mapping
