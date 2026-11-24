# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Chassis NetworkAdapter Port normalizer: DMTF ``#Port`` at ``.../NetworkAdapters/{id}/Ports``.

``Port`` replaces the deprecated ``NetworkPort``. Redpool serves it at ``Ports`` on every
BMC, and vendor port data is normalized here, never at ``NetworkPorts``.
"""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import omit_if_null, optional
from ..network_ports.base import (
    COLLECTION_MAPPING as NETWORK_PORT_COLLECTION_MAPPING,
)
from ..network_ports.base import (
    effective_port_current_speed_gbps,
    effective_port_id,
    effective_port_link_network_technology,
    port_ethernet,
    port_link_status,
)


class BasePortNormalizer(ResourceNormalizer):
    """Port (v1_20_0). The field map is one literal schema, with no branching on input type."""

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": optional("@odata.context"),
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Port.v1_20_0.Port",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "LinkNetworkTechnology": omit_if_null(
                effective_port_link_network_technology
            ),
            "CurrentSpeedGbps": effective_port_current_speed_gbps,
            "PortId": effective_port_id,
            "Ethernet": port_ethernet,
            "LinkStatus": omit_if_null(port_link_status),
            "MaxFrameSize": optional("MaxFrameSize"),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


PORT_COLLECTION_MAPPING: Dict[str, Any] = {
    **NETWORK_PORT_COLLECTION_MAPPING,
    "@odata.context": "/redfish/v1/$metadata#PortCollection.PortCollection",
    "@odata.type": "#PortCollection.PortCollection",
    "Description": "Collection of Ports",
    "Name": "Ports Collection",
}
