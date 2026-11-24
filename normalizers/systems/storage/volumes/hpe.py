# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE SmartStorage LogicalDrive to standard Volume normalizer."""

from __future__ import annotations

from typing import Any, Dict, Optional

from redpool.redfish_client import redfish_get_json

from ....types import NormalizationContext
from .._hpe_smartstorage import (
    build_volume_resource,
    hpe_smartstorage_path,
    native_member_for_path,
)
from .base import BaseVolumeNormalizer


class HPEVolumeNormalizer(BaseVolumeNormalizer):
    """Normalize an HPE SmartStorage LogicalDrive as a Redfish Volume."""

    def prefetch(self, ctx: NormalizationContext) -> None:
        if ctx.client is None:
            return
        parts = ctx.odata_id.split("/Systems/", 1)
        if (
            len(parts) != 2
            or "/Storage/" not in parts[1]
            or "/Volumes/" not in parts[1]
        ):
            return
        system_id = parts[1].split("/", 1)[0]
        suffix = parts[1].split("/Storage/", 1)[1].split("/")
        if len(suffix) < 3:
            return
        storage_id = suffix[0]
        volume_id = suffix[2]
        ctx.prefetched["data_drives"] = redfish_get_json(
            ctx.client,
            hpe_smartstorage_path(
                system_id,
                "ArrayControllers",
                storage_id,
                "LogicalDrives",
                volume_id,
                "DataDrives",
            ),
        )
        ctx.prefetched["system_id"] = system_id
        ctx.prefetched["storage_id"] = storage_id
        ctx.prefetched["native"] = native_member_for_path(ctx.client, ctx.odata_id)

    def normalized_body_from_prefetch(
        self,
        ctx: NormalizationContext,
    ) -> Optional[Dict[str, Any]]:
        return build_volume_resource(
            ctx.odata_id,
            ctx.data,
            data_drives=ctx.prefetched.get("data_drives"),
            system_id=ctx.prefetched.get("system_id"),
            storage_id=ctx.prefetched.get("storage_id"),
            native=ctx.prefetched.get("native"),
        )
