# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base BootOption normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseBootOptionNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#BootOption.BootOption",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#BootOption.v1_0_4.BootOption",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "BootOptionEnabled": optional("BootOptionEnabled"),
            "BootOptionReference": optional("BootOptionReference"),
            "DisplayName": optional("DisplayName"),
            "UefiDevicePath": optional("UefiDevicePath"),
            "RelatedItem": lambda ctx: ctx.data.get("RelatedItem", []),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#BootOptionCollection.BootOptionCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#BootOptionCollection.BootOptionCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Boot Options",
    "Name": "BootOptionCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
