# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE SmartStorage ArrayController to standard StorageController normalizer."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from redpool.redfish_client import redfish_get_json

from ....types import NormalizationContext
from .._hpe_smartstorage import (
    build_storage_controller_resource,
    hpe_batteries_from_chassis,
    hpe_chassis_path,
    native_controller,
    storage_id_from_array_controller,
)
from .base import BaseStorageControllerNormalizer


def _controller_ids(ctx: NormalizationContext) -> Tuple[Optional[str], str]:
    """``(system_id, storage_id)`` of this ArrayController URL and its data."""
    parts = ctx.odata_id.split("/Systems/", 1)
    system_id = None
    storage_id = storage_id_from_array_controller(ctx.data)
    if len(parts) == 2:
        system_id = parts[1].split("/", 1)[0]
        if "/Storage/" in parts[1]:
            storage_id = parts[1].split("/Storage/", 1)[1].split("/", 1)[0]
    return system_id, storage_id


class HPEStorageControllerNormalizer(BaseStorageControllerNormalizer):
    """Normalize an HPE SmartStorage ArrayController as a Redfish StorageController."""

    def prefetch(self, ctx: NormalizationContext) -> None:
        if ctx.client is None:
            return
        system_id, storage_id = _controller_ids(ctx)
        ctx.prefetched["chassis"] = redfish_get_json(
            ctx.client, hpe_chassis_path(ctx.client, system_id or "")
        )
        if system_id:
            ctx.prefetched["native"] = native_controller(
                ctx.client, system_id, storage_id
            )

    def normalized_body_from_prefetch(
        self,
        ctx: NormalizationContext,
    ) -> Optional[Dict[str, Any]]:
        system_id, storage_id = _controller_ids(ctx)
        chassis = ctx.prefetched.get("chassis") or {}
        return build_storage_controller_resource(
            ctx.odata_id,
            ctx.data,
            battery_count=len(hpe_batteries_from_chassis(chassis)),
            system_id=system_id,
            storage_id=storage_id,
            native=ctx.prefetched.get("native"),
        )
