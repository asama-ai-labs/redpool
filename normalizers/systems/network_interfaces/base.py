# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base NetworkInterface normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseNetworkInterfaceNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#NetworkInterface.NetworkInterface",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#NetworkInterface.v1_2_0.NetworkInterface",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "NetworkDeviceFunctions": lambda ctx: ctx.data.get(
                "NetworkDeviceFunctions", {}
            ),
            "NetworkPorts": lambda ctx: ctx.data.get("NetworkPorts", {}),
            "Ports": lambda ctx: ctx.data.get("Ports", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#NetworkInterfaceCollection.NetworkInterfaceCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#NetworkInterfaceCollection.NetworkInterfaceCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Network Interfaces",
    "Name": "NetworkInterfaceCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
