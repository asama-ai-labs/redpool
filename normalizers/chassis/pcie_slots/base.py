# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base PCIeSlots normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BasePCIeSlotsNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#PCIeSlots.PCIeSlots",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#PCIeSlots.v1_5_0.PCIeSlots",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Slots": lambda ctx: ctx.data.get("Slots", []),
            "Slots@odata.count": optional("Slots@odata.count"),
        }
