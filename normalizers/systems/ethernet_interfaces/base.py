# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base EthernetInterface normalizer for System-level interfaces.

Covers physical NIC ports exposed under ``/Systems/{id}/EthernetInterfaces``.
The Manager-level normalizer subclasses this and adds BMC-specific fields.
"""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import omit_if_null, optional
from ...chassis.network_ports.base import canonicalize_ethernet_link_status


class BaseEthernetInterfaceNormalizer(ResourceNormalizer):
    """Vendor-agnostic System EthernetInterface normalizer."""

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#EthernetInterface.EthernetInterface",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#EthernetInterface.v1_12_1.EthernetInterface",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "MACAddress": lambda ctx: ctx.data.get("MACAddress"),
            "PermanentMACAddress": lambda ctx: ctx.data.get("PermanentMACAddress"),
            "LinkStatus": omit_if_null(
                lambda ctx: canonicalize_ethernet_link_status(
                    ctx.data.get("LinkStatus")
                )
            ),
            "InterfaceEnabled": optional("InterfaceEnabled"),
            "SpeedMbps": lambda ctx: ctx.data.get("SpeedMbps"),
            "FullDuplex": optional("FullDuplex"),
            "AutoNeg": lambda ctx: ctx.data.get("AutoNeg"),
            "MTUSize": optional("MTUSize"),
            "EthernetInterfaceType": optional("EthernetInterfaceType"),
            "FQDN": optional("FQDN"),
            "HostName": optional("HostName"),
            "IPv4Addresses": lambda ctx: ctx.data.get("IPv4Addresses", []),
            "IPv4StaticAddresses": lambda ctx: ctx.data.get("IPv4StaticAddresses", []),
            "IPv6Addresses": lambda ctx: ctx.data.get("IPv6Addresses", []),
            "IPv6StaticAddresses": lambda ctx: ctx.data.get("IPv6StaticAddresses", []),
            "IPv6DefaultGateway": optional("IPv6DefaultGateway"),
            "NameServers": lambda ctx: ctx.data.get("NameServers", []),
            "VLAN": lambda ctx: ctx.data.get("VLAN", {}),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#EthernetInterfaceCollection.EthernetInterfaceCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#EthernetInterfaceCollection.EthernetInterfaceCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Ethernet Interfaces",
    "Name": "EthernetInterfaceCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
