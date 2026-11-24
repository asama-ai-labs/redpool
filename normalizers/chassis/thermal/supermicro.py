# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Supermicro-specific Thermal normalizer.

Merges 12 fan entries (6 RPM + 6 PWM) into 6 physical fans but outputs 12 array
entries so the collector emits both redfish_thermal_fan_speed_rpm and
redfish_thermal_fan_speed_percent for the same 6 fans (additional metrics per fan).
"""

from __future__ import annotations

from typing import Any, Dict, List

from ...types import NormalizationContext
from .base import BaseThermalNormalizer, normalize_fan


def _reading_units(fan: Any) -> str:
    if not isinstance(fan, dict):
        return ""
    u = fan.get("ReadingUnits") or ""
    return str(u).strip()


def _normalize_fans_supermicro(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    """Merge RPM+PWM pairs into 6 physical fans; emit 12 entries (RPM + Percent per fan)."""
    raw = ctx.data.get("Fans") or []
    if not isinstance(raw, list):
        return []
    rpm_fans = [x for x in raw if _reading_units(x) == "RPM"]
    pct_fans = [x for x in raw if _reading_units(x) in ("Percent", "Percentage")]
    if not rpm_fans or len(rpm_fans) != len(pct_fans):
        return [normalize_fan(x) for x in raw]
    out: List[Dict[str, Any]] = []
    for i in range(len(rpm_fans)):
        r = normalize_fan(rpm_fans[i])
        out.append(r)
        name = r.get("Name") or r.get("FanName") or ""
        reading = (
            pct_fans[i].get("Reading")
            if pct_fans[i].get("Reading") is not None
            else pct_fans[i].get("CurrentReading")
        )
        if reading is not None and name:
            pct_entry = dict(pct_fans[i])
            pct_entry["Name"] = name
            pct_entry["FanName"] = name
            pct_entry["Reading"] = reading
            pct_entry["ReadingUnits"] = "Percent"
            out.append(normalize_fan(pct_entry))
    return out


class SupermicroThermalNormalizer(BaseThermalNormalizer):
    """Thermal normalizer for Supermicro: 6 physical fans with both RPM and Percent metrics."""

    def field_map(self) -> Dict[str, Any]:
        base = super().field_map()
        base["Fans"] = _normalize_fans_supermicro
        base["Fans@odata.count"] = lambda ctx: len(_normalize_fans_supermicro(ctx))
        return base
