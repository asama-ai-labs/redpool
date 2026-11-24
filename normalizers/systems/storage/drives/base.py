# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Drive normalizer for Storage-level drives.

Reuses the same Drive schema as Chassis/Drives.
"""

from __future__ import annotations

from typing import Any, Dict

from ....base import ResourceNormalizer
from ....chassis.drives.base import drive_field_map
from ....optional import optional


class BaseStorageDriveNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return drive_field_map()


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#DriveCollection.DriveCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#DriveCollection.DriveCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Drives",
    "Name": "DriveCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
