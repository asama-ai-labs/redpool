# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base SecureBoot normalizer (singleton sub-resource)."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseSecureBootNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#SecureBoot.SecureBoot",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#SecureBoot.v1_1_0.SecureBoot",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "SecureBootEnable": optional("SecureBootEnable"),
            "SecureBootCurrentBoot": optional("SecureBootCurrentBoot"),
            "SecureBootMode": optional("SecureBootMode"),
            "SecureBootDatabases": lambda ctx: ctx.data.get("SecureBootDatabases", {}),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }
