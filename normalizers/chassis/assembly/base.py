# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Assembly normalizer (FRU / physical component data)."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseAssemblyNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Assembly.Assembly",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Assembly.v1_5_1.Assembly",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Assemblies": lambda ctx: ctx.data.get("Assemblies", []),
            "Assemblies@odata.count": optional("Assemblies@odata.count"),
        }
