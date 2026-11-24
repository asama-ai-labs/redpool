# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Manager-level EthernetInterface normalizer.

Extends the System-level normalizer with BMC management fields
(DHCP configuration, static DNS, VLAN, etc.).
"""

from __future__ import annotations

from typing import Any, Dict

from ...optional import optional
from ...systems.ethernet_interfaces.base import (
    COLLECTION_MAPPING as _SYS_COLLECTION_MAPPING,
)
from ...systems.ethernet_interfaces.base import (
    BaseEthernetInterfaceNormalizer,
)


class BaseManagerEthernetNormalizer(BaseEthernetInterfaceNormalizer):
    """Manager EthernetInterface — adds BMC-specific fields."""

    def field_map(self) -> Dict[str, Any]:
        base = super().field_map()
        base.update(
            {
                "DHCPv4": lambda ctx: ctx.data.get("DHCPv4", {}),
                "DHCPv6": lambda ctx: ctx.data.get("DHCPv6", {}),
                "StaticNameServers": lambda ctx: ctx.data.get("StaticNameServers", []),
                "IPv6AddressPolicyTable": lambda ctx: ctx.data.get(
                    "IPv6AddressPolicyTable", []
                ),
                "IPv6StaticDefaultGateways": lambda ctx: ctx.data.get(
                    "IPv6StaticDefaultGateways", []
                ),
                "StatelessAddressAutoConfig": lambda ctx: ctx.data.get(
                    "StatelessAddressAutoConfig", {}
                ),
                "MaxIPv6StaticAddresses": optional("MaxIPv6StaticAddresses"),
                "VLANs": lambda ctx: ctx.data.get("VLANs", {}),
            }
        )
        return base


COLLECTION_MAPPING: Dict[str, Any] = _SYS_COLLECTION_MAPPING
