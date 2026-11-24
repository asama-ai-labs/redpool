# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE-specific Power normalizer.

HPE iLO often reports the same Name ("HpeServerPowerSupply") for every PSU.
This normalizer sets Name from Oem.Hpe.BayNumber (e.g. "PSU Bay 1") or
fallback to "PSU {MemberId}" when Name is generic so each PSU has a distinct label.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...types import NormalizationContext
from .base import BasePowerNormalizer, normalize_power_supplies

_GENERIC_HPE_PSU_NAME = "HpeServerPowerSupply"


def _normalize_psu_name_hpe(item: Dict[str, Any]) -> str | None:
    """Return a distinct PSU name from Oem.Hpe.BayNumber or MemberId when Name is generic."""
    name = (item.get("Name") or "").strip()
    if name and name != _GENERIC_HPE_PSU_NAME:
        return name
    oem = item.get("Oem") or {}
    hpe = oem.get("Hpe") or oem.get("HPE") or {}
    bay = hpe.get("BayNumber")
    if bay is not None:
        return f"PSU Bay {bay}"
    member_id = item.get("MemberId") or item.get("MemberID")
    if member_id is not None:
        return f"PSU {member_id}"
    return name or "PSU"


def hot_pluggable_from_hpe_oem(item: Dict[str, Any]) -> Optional[bool]:
    """Map Oem.Hpe.HotplugCapable → HotPluggable when standard field is absent."""
    if item.get("HotPluggable") is not None:
        return None
    oem = item.get("Oem")
    if not isinstance(oem, dict):
        return None
    for vendor_key in ("Hpe", "HPE", "Hp"):
        block = oem.get(vendor_key)
        if isinstance(block, dict):
            for key in ("HotplugCapable", "HotPlugCapable", "HotPluggable"):
                v = block.get(key)
                if isinstance(v, bool):
                    return v
    return None


def _normalize_power_supplies_hpe(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    """Same as base normalize_power_supplies, then set a distinct Name for each PSU."""
    supplies = normalize_power_supplies(ctx)
    for s in supplies:
        name = _normalize_psu_name_hpe(s)
        if name is not None:
            s["Name"] = name
        hot = hot_pluggable_from_hpe_oem(s)
        if hot is not None:
            s["HotPluggable"] = hot
    return supplies


class HPEPowerNormalizer(BasePowerNormalizer):
    def field_map(self) -> Dict[str, Any]:
        base_map = super().field_map()
        base_map["PowerSupplies"] = _normalize_power_supplies_hpe
        return base_map
