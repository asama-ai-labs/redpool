# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base PowerSupply normalizer (new-Redfish via PowerSubsystem)."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional
from ...types import NormalizationContext
from ...vendor_id import manufacturer_from_model, normalize_power_supply_manufacturer
from ..power.base import power_supply_hot_pluggable


def _part_number_or_spare(ctx: NormalizationContext) -> Any:
    pn = ctx.data.get("PartNumber")
    if isinstance(pn, str):
        if pn.strip():
            return pn
    elif pn is not None:
        return pn
    spare = ctx.data.get("SparePartNumber")
    if isinstance(spare, str):
        s = spare.strip()
        return s if s else None
    return spare


def _power_supply_manufacturer(ctx: NormalizationContext) -> Any:
    """PSU ``Manufacturer`` from the payload only. The server vendor is not the PSU maker."""
    m = ctx.data.get("Manufacturer")
    if isinstance(m, str) and m.strip():
        return normalize_power_supply_manufacturer(m.strip())
    if m is not None and not isinstance(m, str):
        return m
    return manufacturer_from_model(ctx.data.get("Model"))


class BasePowerSupplyNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#PowerSupply.PowerSupply",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#PowerSupply.v1_5_0.PowerSupply",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Model": optional("Model"),
            "Manufacturer": _power_supply_manufacturer,
            "SerialNumber": optional("SerialNumber"),
            "PartNumber": _part_number_or_spare,
            "SparePartNumber": optional("SparePartNumber"),
            "FirmwareVersion": optional("FirmwareVersion"),
            "PowerCapacityWatts": optional("PowerCapacityWatts"),
            "PowerSupplyType": optional("PowerSupplyType"),
            "InputNominalVoltageType": optional("InputNominalVoltageType"),
            "LineInputStatus": optional("LineInputStatus"),
            "EfficiencyRatings": lambda ctx: ctx.data.get("EfficiencyRatings", []),
            "HotPluggable": lambda ctx: power_supply_hot_pluggable(ctx.data),
            "Location": lambda ctx: ctx.data.get("Location", {}),
            "LocationIndicatorActive": optional("LocationIndicatorActive"),
            "Metrics": lambda ctx: ctx.data.get("Metrics", {}),
            "Assembly": lambda ctx: ctx.data.get("Assembly", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#PowerSupplyCollection.PowerSupplyCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#PowerSupplyCollection.PowerSupplyCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Power Supplies",
    "Name": "PowerSupplyCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
