# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base storage normalizer.

Storage resources vary somewhat across vendors (older schemas use
``StorageControllers`` arrays, newer ones use a ``Controllers`` link).
The base normalizer passes through both so the output is complete
regardless of schema version.
"""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseStorageNormalizer(ResourceNormalizer):
    """Vendor-agnostic Storage normalizer."""

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Storage.Storage",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Storage.v1_16_0.Storage",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Drives": lambda ctx: ctx.data.get("Drives", []),
            "Drives@odata.count": optional("Drives@odata.count"),
            "Volumes": lambda ctx: ctx.data.get("Volumes", {}),
            "StorageControllers": lambda ctx: ctx.data.get("StorageControllers", []),
            "StorageControllers@odata.count": optional(
                "StorageControllers@odata.count"
            ),
            "Controllers": lambda ctx: ctx.data.get("Controllers", {}),
            "Identifiers": lambda ctx: ctx.data.get("Identifiers") or [],
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#StorageCollection.StorageCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#StorageCollection.StorageCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Storage subsystems",
    "Name": "StorageCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
