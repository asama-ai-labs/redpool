# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE SmartStorage DiskDrive served as standard Drive."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ....base import ResourceNormalizer
from ....optional import optional
from ....types import NormalizationContext
from ...storage._hpe_smartstorage import (
    build_drive_resource,
    hpe_smartstorage_member_parts,
    native_member_for_path,
)


def _client_path(ctx: NormalizationContext) -> str:
    return (ctx.resource_path or ctx.odata_id).rstrip("/")


class BaseSmartStorageDiskDriveNormalizer(ResourceNormalizer):
    """Return the same Drive document the canonical Storage URL serves."""

    def prefetch(self, ctx: NormalizationContext) -> None:
        ctx.prefetched["native"] = native_member_for_path(ctx.client, _client_path(ctx))

    def normalized_body_from_prefetch(
        self, ctx: NormalizationContext
    ) -> Optional[Dict[str, Any]]:
        path = _client_path(ctx)
        parsed = hpe_smartstorage_member_parts(path)
        if parsed is None:
            return None
        _system_id, _storage_id, kind, member_id = parsed
        if kind != "DiskDrives" or not member_id:
            return None
        return build_drive_resource(path, ctx.data, native=ctx.prefetched.get("native"))

    def field_map(self) -> Dict[str, Any]:
        return {"@odata.id": lambda ctx: ctx.odata_id}


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
