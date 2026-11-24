# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base HostInterface normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseHostInterfaceNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#HostInterface.HostInterface",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#HostInterface.v1_3_0.HostInterface",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "InterfaceEnabled": optional("InterfaceEnabled"),
            "HostInterfaceType": optional("HostInterfaceType"),
            "ExternallyAccessible": optional("ExternallyAccessible"),
            "AuthenticationModes": lambda ctx: ctx.data.get("AuthenticationModes", []),
            "HostEthernetInterfaces": lambda ctx: ctx.data.get(
                "HostEthernetInterfaces", {}
            ),
            "ManagerEthernetInterface": lambda ctx: ctx.data.get(
                "ManagerEthernetInterface", {}
            ),
            "NetworkProtocol": lambda ctx: ctx.data.get("NetworkProtocol", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#HostInterfaceCollection.HostInterfaceCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#HostInterfaceCollection.HostInterfaceCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Host Interfaces",
    "Name": "HostInterfaceCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
