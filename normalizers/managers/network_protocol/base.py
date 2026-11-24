# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base NetworkProtocol normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseNetworkProtocolNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#ManagerNetworkProtocol.ManagerNetworkProtocol",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#ManagerNetworkProtocol.v1_9_0.ManagerNetworkProtocol",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "HostName": optional("HostName"),
            "FQDN": optional("FQDN"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "HTTP": lambda ctx: ctx.data.get("HTTP", {}),
            "HTTPS": lambda ctx: ctx.data.get("HTTPS", {}),
            "SSH": lambda ctx: ctx.data.get("SSH", {}),
            "SNMP": lambda ctx: ctx.data.get("SNMP", {}),
            "IPMI": lambda ctx: ctx.data.get("IPMI", {}),
            "KVMIP": lambda ctx: ctx.data.get("KVMIP", {}),
            "NTP": lambda ctx: ctx.data.get("NTP", {}),
            "DHCP": lambda ctx: ctx.data.get("DHCP", {}),
            "DHCPv6": lambda ctx: ctx.data.get("DHCPv6", {}),
            "SSDP": lambda ctx: ctx.data.get("SSDP", {}),
            "Telnet": lambda ctx: ctx.data.get("Telnet", {}),
            "VirtualMedia": lambda ctx: ctx.data.get("VirtualMedia", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }
