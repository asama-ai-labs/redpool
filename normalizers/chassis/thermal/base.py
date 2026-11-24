# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Thermal normalizer (old-style monolithic Thermal resource).

Contains embedded arrays: Temperatures, Fans, Redundancy.
Fishymetrics expects top-level Status (State, Health) for redfish_thermal_summary_status;
some BMCs send HealthRollup instead of Health, so we normalize to Health.

Fans and Temperatures are normalized to canonical field names so clients can rely on
Name, Reading (fans) and ReadingCelsius (temperatures) plus Status.
"""

from __future__ import annotations

from typing import Any, Dict, List

from redpool.redfish_client import redfish_get_json

from ...base import ResourceNormalizer
from ...optional import optional
from ...types import NormalizationContext


def _thermal_status(ctx: NormalizationContext) -> Dict[str, Any]:
    """Return Status with Health from Health or HealthRollup for fishymetrics thermal summary.

    A Thermal resource with no Status takes the sibling ThermalSubsystem's Status, read in
    prefetch. The subsystem reports the same health for the same chassis.
    """
    raw = ctx.data.get("Status") or ctx.prefetched.get("thermal_subsystem_status") or {}
    if not isinstance(raw, dict):
        return {}
    health = raw.get("Health") or raw.get("HealthRollup")
    return {
        "State": raw.get("State"),
        "Health": health,
    }


def normalize_fan(item: Any) -> Dict[str, Any]:
    """Return fan with canonical Name and Reading (from FanName/Name, CurrentReading/Reading).
    Strips trailing ' Tach' from fan names (e.g. Lenovo 'Fan 1A Tach' -> 'Fan 1A')."""
    if not isinstance(item, dict):
        return {}
    out = dict(item)
    name = (item.get("FanName") or item.get("Name")) or ""
    if name.endswith(" Tach"):
        name = name[: -len(" Tach")].rstrip()
    out["Name"] = name
    out["FanName"] = name
    reading = (
        item.get("CurrentReading")
        if item.get("CurrentReading") is not None
        else item.get("Reading")
    )
    if reading is not None:
        out["Reading"] = reading
    if item.get("CurrentReading") is not None:
        out["CurrentReading"] = item["CurrentReading"]
    return out


def _normalize_temperature(item: Any) -> Dict[str, Any]:
    """Return temperature with canonical Name, ReadingCelsius, Status."""
    if not isinstance(item, dict):
        return {}
    out = dict(item)
    out["Name"] = out.get("Name") or ""
    out["ReadingCelsius"] = item.get("ReadingCelsius")
    out["Status"] = item.get("Status") or {}
    return out


def _normalize_fans(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    raw = ctx.data.get("Fans") or []
    if not isinstance(raw, list):
        return []
    return [normalize_fan(x) for x in raw]


def _normalize_temperatures(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    raw = ctx.data.get("Temperatures") or []
    if not isinstance(raw, list):
        return []
    return [_normalize_temperature(x) for x in raw]


class BaseThermalNormalizer(ResourceNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        if ctx.client is None or ctx.data.get("Status"):
            return
        if not ctx.odata_id.endswith("/Thermal"):
            return
        try:
            subsystem = redfish_get_json(ctx.client, ctx.odata_id + "Subsystem")
        except Exception:
            return
        status = subsystem.get("Status") if isinstance(subsystem, dict) else None
        if isinstance(status, dict):
            ctx.prefetched["thermal_subsystem_status"] = status

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Thermal.Thermal",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Thermal.v1_7_3.Thermal",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Status": _thermal_status,
            "Temperatures": _normalize_temperatures,
            "Temperatures@odata.count": optional("Temperatures@odata.count"),
            "Fans": _normalize_fans,
            "Fans@odata.count": optional("Fans@odata.count"),
            "Redundancy": lambda ctx: ctx.data.get("Redundancy", []),
            "Redundancy@odata.count": optional("Redundancy@odata.count"),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }
