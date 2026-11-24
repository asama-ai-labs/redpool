# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base manager (BMC / iDRAC / iLO / XCC) normalizer.

Manager resources are well-standardized across vendors.  The base
normalizer covers all common fields; vendor-specific extensions live in
the Oem namespace which is preserved as-is.
"""

from __future__ import annotations

from typing import Any, Dict

from ..base import ResourceNormalizer
from ..optional import optional
from ..types import NormalizationContext
from ..vendor_id import canonical_server_vendor, manufacturer_display_name


def _canonical_manager_manufacturer(data: dict, *, oem: dict) -> str | None:
    mfg = data.get("Manufacturer")
    if isinstance(mfg, str) and mfg.strip():
        raw = mfg.strip()
    else:
        raw = ""

    if not raw:
        # Prefer OEM vendor key (stable) when Manufacturer is missing.
        for k in (oem or {}).keys():
            if isinstance(k, str) and k.strip():
                raw = k.strip()
                break

    if not raw:
        return None

    return canonical_server_vendor(raw)


def _manager_manufacturer(ctx: NormalizationContext) -> str | None:
    oem = ctx.data.get("Oem") or (ctx.data.get("Links") or {}).get("Oem") or {}
    manufacturer = _canonical_manager_manufacturer(ctx.data, oem=oem)
    if (manufacturer or "").lower() in ("openbmc", "openbmc project", "open-bmc"):
        return ctx.vendor if isinstance(ctx.vendor, str) and ctx.vendor else None
    if manufacturer is None:
        return None
    return manufacturer_display_name(manufacturer)


class BaseManagerNormalizer(ResourceNormalizer):
    """Vendor-agnostic Manager normalizer."""

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Manager.Manager",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Manager.v1_19_1.Manager",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Manufacturer": _manager_manufacturer,
            "ManagerType": optional("ManagerType"),
            "Model": optional("Model"),
            "FirmwareVersion": optional("FirmwareVersion"),
            "UUID": optional("UUID"),
            "DateTime": optional("DateTime"),
            "DateTimeLocalOffset": optional("DateTimeLocalOffset"),
            "PowerState": optional("PowerState"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
            "EthernetInterfaces": lambda ctx: ctx.data.get("EthernetInterfaces", {}),
            "NetworkProtocol": lambda ctx: ctx.data.get("NetworkProtocol", {}),
            "HostInterfaces": lambda ctx: ctx.data.get("HostInterfaces", {}),
            "SerialInterfaces": lambda ctx: ctx.data.get("SerialInterfaces", {}),
            "VirtualMedia": lambda ctx: ctx.data.get("VirtualMedia", {}),
            "LogServices": lambda ctx: ctx.data.get("LogServices", {}),
            "GraphicalConsole": lambda ctx: ctx.data.get("GraphicalConsole", {}),
            "SerialConsole": lambda ctx: ctx.data.get("SerialConsole", {}),
            "CommandShell": lambda ctx: ctx.data.get("CommandShell", {}),
            "Redundancy": lambda ctx: ctx.data.get("Redundancy", []),
            # Some vendors only expose OEM vendor keys under Links.Oem (not top-level Oem).
            # Promote Links.Oem to Oem so downstream collectors can consistently infer vendor.
            "Oem": lambda ctx: (
                ctx.data.get("Oem") or (ctx.data.get("Links") or {}).get("Oem", {})
            ),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#ManagerCollection.ManagerCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#ManagerCollection.ManagerCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Managers",
    "Name": "ManagerCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
