# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo Chassis Power: correct per-PSU DC output in embedded ``PowerSupplies``.

Some Lenovo BMCs set ``LastPowerOutputWatts`` on every supply to the chassis
aggregate (often matching ``PowerControl[0].PowerMetrics.AverageConsumedWatts``)
while ``PowerOutputWatts`` holds each PSU's DC output. The base normalizer
prefers a non-zero ``LastPowerOutputWatts``, which preserves the bogus value.
When ``LastPowerOutputWatts`` is much larger than ``PowerOutputWatts``, treat
``PowerOutputWatts`` as the per-supply reading and copy it onto
``LastPowerOutputWatts`` so collectors and clients see consistent per-PSU watts.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ...types import NormalizationContext
from .base import BasePowerNormalizer, normalize_power_supply


def _lenovo_clarify_supply_output_watts(item: Dict[str, Any]) -> Dict[str, Any]:
    """If *LastPowerOutputWatts* looks like a repeated chassis total, use *PowerOutputWatts*."""
    last = item.get("LastPowerOutputWatts")
    po = item.get("PowerOutputWatts")
    if not isinstance(last, (int, float)) or not isinstance(po, (int, float)):
        return item
    if po <= 0 or last <= 0:
        return item
    # Per-PSU DC is on PowerOutputWatts; Last repeats chassis average (see SR680a).
    if last <= po * 1.5:
        return item
    out = dict(item)
    out["LastPowerOutputWatts"] = po
    return out


def _extend_psu_redpool_fru_from_lenovo(item: Dict[str, Any]) -> Dict[str, Any]:
    """Copy Oem.Lenovo.FruPartNumber into Oem.Redpool.FruPartNumber."""
    oem = item.get("Oem")
    if not isinstance(oem, dict):
        return item
    lnv = oem.get("Lenovo")
    if not isinstance(lnv, dict):
        return item
    fru = lnv.get("FruPartNumber")
    if not isinstance(fru, str) or not fru.strip():
        return item
    out = dict(item)
    oem_out = dict(oem)
    rp = oem_out.get("Redpool")
    rp_out = dict(rp) if isinstance(rp, dict) else {}
    rp_out["FruPartNumber"] = fru.strip()
    oem_out["Redpool"] = rp_out
    out["Oem"] = oem_out
    return out


def _normalize_power_supplies_lenovo(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    raw = ctx.data.get("PowerSupplies") or []
    if not isinstance(raw, list) or not raw:
        prefetched = ctx.prefetched.get("PowerSupplies") if ctx.prefetched else None
        if isinstance(prefetched, list) and prefetched:
            raw = prefetched
        else:
            return []
    out: List[Dict[str, Any]] = []
    for x in raw:
        if not isinstance(x, dict):
            continue
        n = normalize_power_supply(x, ctx)
        n = _lenovo_clarify_supply_output_watts(n)
        n = _extend_psu_redpool_fru_from_lenovo(n)
        out.append(n)
    return out


def _power_supplies_count_lenovo(ctx: NormalizationContext) -> Any:
    supplies = _normalize_power_supplies_lenovo(ctx)
    return len(supplies) if supplies else ctx.data.get("PowerSupplies@odata.count")


class LenovoPowerNormalizer(BasePowerNormalizer):
    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["PowerSupplies"] = _normalize_power_supplies_lenovo
        m["PowerSupplies@odata.count"] = _power_supplies_count_lenovo
        return m
