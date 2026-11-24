# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base NetworkAdapter normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseNetworkAdapterNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#NetworkAdapter.NetworkAdapter",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#NetworkAdapter.v1_11_0.NetworkAdapter",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Manufacturer": optional("Manufacturer"),
            "Model": optional("Model"),
            "SerialNumber": optional("SerialNumber"),
            "PartNumber": optional("PartNumber"),
            "SKU": optional("SKU"),
            "Controllers": lambda ctx: ctx.data.get("Controllers", []),
            "NetworkDeviceFunctions": lambda ctx: ctx.data.get(
                "NetworkDeviceFunctions", {}
            ),
            "NetworkPorts": lambda ctx: ctx.data.get("NetworkPorts", {}),
            "Ports": lambda ctx: ctx.data.get("Ports", {}),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Assembly": lambda ctx: ctx.data.get("Assembly", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#NetworkAdapterCollection.NetworkAdapterCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#NetworkAdapterCollection.NetworkAdapterCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Network Adapters",
    "Name": "NetworkAdapterCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
