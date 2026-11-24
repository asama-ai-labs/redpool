# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base StorageController normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ....base import ResourceNormalizer
from ....optional import OMIT, optional


def _cache_summary(ctx: Any) -> Any:
    summary = ctx.data.get("CacheSummary")
    if not isinstance(summary, dict):
        return OMIT
    kept = {key: value for key, value in summary.items() if value is not None}
    if not kept:
        return OMIT
    return kept


class BaseStorageControllerNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#StorageController.StorageController",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#StorageController.v1_7_0.StorageController",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Manufacturer": optional("Manufacturer"),
            "Model": optional("Model"),
            "SerialNumber": optional("SerialNumber"),
            "PartNumber": optional("PartNumber"),
            "FirmwareVersion": optional("FirmwareVersion"),
            "Identifiers": lambda ctx: ctx.data.get("Identifiers") or [],
            "SpeedGbps": optional("SpeedGbps"),
            "SupportedControllerProtocols": lambda ctx: ctx.data.get(
                "SupportedControllerProtocols", []
            ),
            "SupportedDeviceProtocols": lambda ctx: ctx.data.get(
                "SupportedDeviceProtocols", []
            ),
            "SupportedRAIDTypes": lambda ctx: ctx.data.get("SupportedRAIDTypes", []),
            "CacheSummary": _cache_summary,
            "PCIeInterface": lambda ctx: ctx.data.get("PCIeInterface", {}),
            "ControllerRates": lambda ctx: ctx.data.get("ControllerRates", {}),
            "Ports": lambda ctx: ctx.data.get("Ports", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#StorageControllerCollection.StorageControllerCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#StorageControllerCollection.StorageControllerCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Storage Controllers",
    "Name": "StorageControllerCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
