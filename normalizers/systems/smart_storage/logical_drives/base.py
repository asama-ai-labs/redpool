# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE SmartStorage LogicalDrive served as standard Volume."""

from __future__ import annotations

from typing import Any, Dict, Optional

from redpool.redfish_client import redfish_get_json

from ....base import ResourceNormalizer
from ....optional import optional
from ....types import NormalizationContext
from ...storage._hpe_smartstorage import (
    build_volume_resource,
    hpe_smartstorage_member_parts,
    hpe_smartstorage_path,
    native_member_for_path,
)


def _client_path(ctx: NormalizationContext) -> str:
    return (ctx.resource_path or ctx.odata_id).rstrip("/")


class BaseSmartStorageLogicalDriveNormalizer(ResourceNormalizer):
    """Return the same Volume document the canonical Storage URL serves."""

    def prefetch(self, ctx: NormalizationContext) -> None:
        parsed = hpe_smartstorage_member_parts(_client_path(ctx))
        if parsed is None or ctx.client is None:
            return
        system_id, storage_id, kind, member_id = parsed
        if kind != "LogicalDrives" or not member_id:
            return
        try:
            data_drives = redfish_get_json(
                ctx.client,
                hpe_smartstorage_path(
                    system_id,
                    "ArrayControllers",
                    storage_id,
                    "LogicalDrives",
                    member_id,
                    "DataDrives",
                ),
            )
        except Exception:
            data_drives = {}
        if isinstance(data_drives, dict):
            ctx.prefetched["data_drives"] = data_drives
        ctx.prefetched["native"] = native_member_for_path(ctx.client, _client_path(ctx))

    def normalized_body_from_prefetch(
        self, ctx: NormalizationContext
    ) -> Optional[Dict[str, Any]]:
        path = _client_path(ctx)
        parsed = hpe_smartstorage_member_parts(path)
        if parsed is None:
            return None
        system_id, storage_id, kind, member_id = parsed
        if kind != "LogicalDrives" or not member_id:
            return None
        return build_volume_resource(
            path,
            ctx.data,
            data_drives=ctx.prefetched.get("data_drives"),
            system_id=system_id,
            storage_id=storage_id,
            native=ctx.prefetched.get("native"),
        )

    def field_map(self) -> Dict[str, Any]:
        return {"@odata.id": lambda ctx: ctx.odata_id}


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#VolumeCollection.VolumeCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#VolumeCollection.VolumeCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Volumes",
    "Name": "VolumeCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
