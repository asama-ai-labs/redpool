# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base chassis normalizer.

Chassis resources are relatively standardized across vendors.  The base
normalizer passes through all common fields; vendor-specific data lives
in the Oem namespace which is preserved as-is.
"""

from __future__ import annotations

from typing import Any, Dict

from redpool.redfish_client import redfish_get_json

from ..base import ResourceNormalizer
from ..optional import optional
from ..types import NormalizationContext
from ..vendor_id import manufacturer_from_model, normalize_vendor_id

_SYSTEM_MANUFACTURER_PREFETCH_KEY = "server_manufacturer"
# Chassis types that are a system's own chassis. Enclosures, backplanes and other
# sub-chassis are often made by someone else, so they never take the server vendor.
_SYSTEM_CHASSIS_TYPES = frozenset({"RackMount", "Blade", "StandAlone"})


def _manufacturer_nonempty(data: Dict[str, Any]) -> bool:
    m = data.get("Manufacturer")
    return isinstance(m, str) and bool(m.strip())


def prefetch_chassis_server_manufacturer(ctx: NormalizationContext) -> None:
    """When chassis ``Manufacturer`` is empty, load it from the ComputerSystem this chassis links to.

    Only the linked system is used. Another system on the BMC may belong to a
    different server, so its manufacturer does not describe this chassis.
    """
    ctx.prefetched.pop(_SYSTEM_MANUFACTURER_PREFETCH_KEY, None)
    if _manufacturer_nonempty(ctx.data) or ctx.client is None:
        return
    links = ctx.data.get("Links")
    linked = links.get("ComputerSystems") if isinstance(links, dict) else None
    for ref in linked or []:
        uri = _link_odata_id(ref)
        if not uri:
            continue
        try:
            system = redfish_get_json(ctx.client, uri)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(system, dict):
            continue
        mfr = system.get("Manufacturer")
        if isinstance(mfr, str) and mfr.strip():
            ctx.prefetched[_SYSTEM_MANUFACTURER_PREFETCH_KEY] = mfr.strip()
            return


def _effective_chassis_manufacturer(ctx: NormalizationContext) -> Any:
    """Chassis ``Manufacturer``; else the linked ComputerSystem's; else, for a system's own chassis only, the server vendor."""
    m = ctx.data.get("Manufacturer")
    if isinstance(m, str) and m.strip():
        return normalize_vendor_id(m.strip())
    if m is not None and not isinstance(m, str):
        return m
    pref = (ctx.prefetched or {}).get(_SYSTEM_MANUFACTURER_PREFETCH_KEY)
    if isinstance(pref, str) and pref.strip():
        return normalize_vendor_id(pref.strip())
    inferred = manufacturer_from_model(ctx.data.get("Model"))
    if inferred:
        return inferred
    # Narrow fallback: a system's own chassis with no linked manufacturer is presumed to be
    # the server vendor's. Any other chassis stays unknown.
    if ctx.data.get("ChassisType") in _SYSTEM_CHASSIS_TYPES:
        vendor = (ctx.vendor or "").strip()
        if vendor:
            return normalize_vendor_id(vendor)
    return None


def _link_odata_id(ref: Any) -> str:
    if isinstance(ref, dict):
        oid = ref.get("@odata.id") or ref.get("href")
        if isinstance(oid, str) and oid.strip():
            return oid.strip().split("#")[0]
    return ""


def _has_power_thermal_link(data: Dict[str, Any], key: str) -> bool:
    return bool(_link_odata_id(data.get(key)))


def _hoist_power_thermal_from_contains(ctx: NormalizationContext) -> None:
    """If parent lacks Power/Thermal, copy from the first Contained chassis that has them."""
    if _has_power_thermal_link(ctx.data, "Power") and _has_power_thermal_link(
        ctx.data, "Thermal"
    ):
        return
    if ctx.client is None:
        return
    links = ctx.data.get("Links")
    if not isinstance(links, dict):
        return
    contains = links.get("Contains")
    if not isinstance(contains, list):
        return
    for item in contains[:12]:
        uri = _link_odata_id(item)
        if not uri:
            continue
        try:
            child = redfish_get_json(ctx.client, uri)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(child, dict):
            continue
        if not _has_power_thermal_link(ctx.data, "Power"):
            p = _link_odata_id(child.get("Power"))
            if p:
                ctx.prefetched["hoisted_power"] = {"@odata.id": p}
        if not _has_power_thermal_link(ctx.data, "Thermal"):
            t = _link_odata_id(child.get("Thermal"))
            if t:
                ctx.prefetched["hoisted_thermal"] = {"@odata.id": t}
        if ctx.prefetched.get("hoisted_power") and ctx.prefetched.get(
            "hoisted_thermal"
        ):
            break


def _effective_power(ctx: NormalizationContext) -> Any:
    if _has_power_thermal_link(ctx.data, "Power"):
        return ctx.data.get("Power")
    hoisted = ctx.prefetched.get("hoisted_power") if ctx.prefetched else None
    if isinstance(hoisted, dict) and hoisted.get("@odata.id"):
        return hoisted
    return ctx.data.get("Power", {})


def _effective_thermal(ctx: NormalizationContext) -> Any:
    if _has_power_thermal_link(ctx.data, "Thermal"):
        return ctx.data.get("Thermal")
    hoisted = ctx.prefetched.get("hoisted_thermal") if ctx.prefetched else None
    if isinstance(hoisted, dict) and hoisted.get("@odata.id"):
        return hoisted
    return ctx.data.get("Thermal", {})


class BaseChassisNormalizer(ResourceNormalizer):
    """Vendor-agnostic Chassis normalizer."""

    def prefetch(self, ctx: NormalizationContext) -> None:
        _hoist_power_thermal_from_contains(ctx)
        prefetch_chassis_server_manufacturer(ctx)

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Chassis.Chassis",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Chassis.v1_25_1.Chassis",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "ChassisType": optional("ChassisType"),
            "Manufacturer": _effective_chassis_manufacturer,
            "Model": optional("Model"),
            "SerialNumber": optional("SerialNumber"),
            "PartNumber": optional("PartNumber"),
            "SKU": optional("SKU"),
            "AssetTag": optional("AssetTag"),
            "PowerState": optional("PowerState"),
            "IndicatorLED": optional("IndicatorLED"),
            "LocationIndicatorActive": optional("LocationIndicatorActive"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
            "Power": _effective_power,
            "Thermal": _effective_thermal,
            "PowerSubsystem": lambda ctx: ctx.data.get("PowerSubsystem", {}),
            "ThermalSubsystem": lambda ctx: ctx.data.get("ThermalSubsystem", {}),
            "NetworkAdapters": lambda ctx: ctx.data.get("NetworkAdapters", {}),
            "PCIeDevices": lambda ctx: ctx.data.get("PCIeDevices", {}),
            "PCIeSlots": lambda ctx: ctx.data.get("PCIeSlots", {}),
            "Assembly": lambda ctx: ctx.data.get("Assembly", {}),
            "Sensors": lambda ctx: ctx.data.get("Sensors", {}),
            "EnvironmentMetrics": lambda ctx: ctx.data.get("EnvironmentMetrics", {}),
            "PhysicalSecurity": lambda ctx: ctx.data.get("PhysicalSecurity", {}),
            "LogServices": lambda ctx: ctx.data.get("LogServices", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#ChassisCollection.ChassisCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#ChassisCollection.ChassisCollection",
    "Members": lambda ctx: (
        [] if ctx.data.get("Members") is None else ctx.data.get("Members")
    ),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Chassis",
    "Name": "ChassisCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
