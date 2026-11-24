# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base SerialInterface normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseSerialInterfaceNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#SerialInterface.SerialInterface",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#SerialInterface.v1_2_0.SerialInterface",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "InterfaceEnabled": optional("InterfaceEnabled"),
            "SignalType": optional("SignalType"),
            "BitRate": optional("BitRate"),
            "Parity": optional("Parity"),
            "DataBits": optional("DataBits"),
            "StopBits": optional("StopBits"),
            "FlowControl": optional("FlowControl"),
            "ConnectorType": optional("ConnectorType"),
            "PinOut": optional("PinOut"),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#SerialInterfaceCollection.SerialInterfaceCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#SerialInterfaceCollection.SerialInterfaceCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Serial Interfaces",
    "Name": "SerialInterfaceCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
