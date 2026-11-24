# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base BIOS normalizer (singleton sub-resource)."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseBiosNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Bios.Bios",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Bios.v1_2_0.Bios",
            "@Redfish.Settings": lambda ctx: ctx.data.get("@Redfish.Settings", {}),
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "AttributeRegistry": optional("AttributeRegistry"),
            "Attributes": lambda ctx: ctx.data.get("Attributes", {}),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }
