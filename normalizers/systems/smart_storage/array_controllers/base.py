# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE SmartStorage ArrayController served as standard Storage."""

from __future__ import annotations

from typing import Any, Dict, Optional

from redpool.redfish_client import redfish_get_json

from ....base import ResourceNormalizer
from ....optional import optional
from ....types import NormalizationContext
from ...storage._hpe_smartstorage import (
    build_storage_resource,
    hpe_smartstorage_member_parts,
    hpe_smartstorage_path,
)


def _client_path(ctx: NormalizationContext) -> str:
    return (ctx.resource_path or ctx.odata_id).rstrip("/")


class BaseSmartStorageArrayControllerNormalizer(ResourceNormalizer):
    """Return the same Storage document the canonical Storage URL serves."""

    def prefetch(self, ctx: NormalizationContext) -> None:
        parsed = hpe_smartstorage_member_parts(_client_path(ctx))
        if parsed is None or ctx.client is None:
            return
        system_id, storage_id, kind, _member = parsed
        if kind:
            return
        try:
            drives = redfish_get_json(
                ctx.client,
                hpe_smartstorage_path(
                    system_id, "ArrayControllers", storage_id, "DiskDrives"
                ),
            )
        except Exception:
            drives = {}
        if isinstance(drives, dict):
            ctx.prefetched["drives"] = drives

    def normalized_body_from_prefetch(
        self, ctx: NormalizationContext
    ) -> Optional[Dict[str, Any]]:
        path = _client_path(ctx)
        parsed = hpe_smartstorage_member_parts(path)
        if parsed is None:
            return None
        system_id, _storage_id, kind, _member = parsed
        if kind:
            return None
        return build_storage_resource(
            path,
            system_id,
            ctx.data,
            disk_collection=ctx.prefetched.get("drives"),
        )

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.id": lambda ctx: ctx.odata_id,
            "Id": lambda ctx: ctx.data.get("Id"),
            "SerialNumber": lambda ctx: (
                ctx.data["SerialNumber"].strip()
                if isinstance(ctx.data.get("SerialNumber"), str)
                else ctx.data.get("SerialNumber")
            ),
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
