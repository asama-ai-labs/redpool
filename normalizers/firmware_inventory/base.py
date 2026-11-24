# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base SoftwareInventory normalizer (used for both Firmware and Software inventory)."""

from __future__ import annotations

from typing import Any, Dict

from ..base import ResourceNormalizer
from ..optional import optional
from ..types import NormalizationContext
from ._shared.firmware_inventory import (
    build_sparse_software_inventory,
    merge_firmware_inventory_oem,
)


class BaseSoftwareInventoryNormalizer(ResourceNormalizer):
    """Vendor-agnostic FirmwareInventory → SoftwareInventory v1_10_2."""

    def normalized_body_from_prefetch(self, ctx: NormalizationContext):
        return build_sparse_software_inventory(ctx)

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#SoftwareInventory.SoftwareInventory",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#SoftwareInventory.v1_10_2.SoftwareInventory",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Version": optional("Version"),
            "VersionString": optional("VersionString"),
            "Updateable": optional("Updateable"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "SoftwareId": optional("SoftwareId"),
            "Manufacturer": optional("Manufacturer"),
            "ReleaseDate": optional("ReleaseDate"),
            "LowestSupportedVersion": optional("LowestSupportedVersion"),
            "UefiDevicePaths": lambda ctx: ctx.data.get("UefiDevicePaths", []),
            "RelatedItem": lambda ctx: ctx.data.get("RelatedItem", []),
            "RelatedItem@odata.count": optional("RelatedItem@odata.count"),
            "WriteProtected": optional("WriteProtected"),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
            "Oem": lambda ctx: merge_firmware_inventory_oem(ctx),
        }


def _firmware_collection_members(ctx: NormalizationContext) -> Any:
    members = ctx.data.get("Members")
    if members is None:
        return []
    return members


def _firmware_collection_count(ctx: NormalizationContext) -> Any:
    supplied = ctx.data.get("Members@odata.count")
    if supplied is not None:
        return supplied
    members = _firmware_collection_members(ctx)
    if isinstance(members, list):
        return len(members)
    return 0


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#SoftwareInventoryCollection.SoftwareInventoryCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#SoftwareInventoryCollection.SoftwareInventoryCollection",
    "Members": _firmware_collection_members,
    "Members@odata.count": _firmware_collection_count,
    "Description": lambda ctx: ctx.data.get(
        "Description", "Collection of Software Inventory"
    ),
    "Name": lambda ctx: ctx.data.get("Name", "SoftwareInventoryCollection"),
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
