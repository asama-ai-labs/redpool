# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base VirtualMedia normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseVirtualMediaNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#VirtualMedia.VirtualMedia",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#VirtualMedia.v1_6_0.VirtualMedia",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "MediaTypes": lambda ctx: ctx.data.get("MediaTypes", []),
            "Image": optional("Image"),
            "ImageName": optional("ImageName"),
            "Inserted": optional("Inserted"),
            "ConnectedVia": optional("ConnectedVia"),
            "WriteProtected": optional("WriteProtected"),
            "TransferMethod": optional("TransferMethod"),
            "TransferProtocolType": optional("TransferProtocolType"),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#VirtualMediaCollection.VirtualMediaCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#VirtualMediaCollection.VirtualMediaCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Virtual Media",
    "Name": "VirtualMediaCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
