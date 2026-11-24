# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Fan normalizer (new-Redfish via ThermalSubsystem)."""

from __future__ import annotations

from typing import Any, Dict

from ..._shared.redpool_oem import oem_with_numeric_redpool
from ...base import ResourceNormalizer
from ...optional import optional
from ...types import NormalizationContext


def _fan_name(ctx: NormalizationContext) -> Any:
    """Prefer Location.PartLocation.ServiceLabel so FanPWM joins Thermal.Fans RPM."""
    data = ctx.data
    location = data.get("Location")
    if isinstance(location, dict):
        part = location.get("PartLocation")
        if isinstance(part, dict):
            label = part.get("ServiceLabel")
            if isinstance(label, str) and label.strip():
                return label.strip()
    name = data.get("Name")
    if name:
        return name
    return data.get("Id")


class BaseFanNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Fan.Fan",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Fan.v1_5_2.Fan",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": _fan_name,
            "Description": optional("Description"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "SpeedPercent": optional("SpeedPercent"),
            "HotPluggable": optional("HotPluggable"),
            "Location": lambda ctx: ctx.data.get("Location", {}),
            "LocationIndicatorActive": optional("LocationIndicatorActive"),
            "Manufacturer": optional("Manufacturer"),
            "Model": optional("Model"),
            "PartNumber": optional("PartNumber"),
            "PhysicalContext": optional("PhysicalContext"),
            "SerialNumber": optional("SerialNumber"),
            "SparePartNumber": optional("SparePartNumber"),
            "Assembly": lambda ctx: ctx.data.get("Assembly", {}),
            "Oem": lambda ctx: oem_with_numeric_redpool(ctx, "FanPWM"),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#FanCollection.FanCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#FanCollection.FanCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Fans",
    "Name": "FanCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
