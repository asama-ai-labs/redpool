# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE SmartStorage DiskDrive to standard Drive normalizer."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ....types import NormalizationContext
from .._hpe_smartstorage import build_drive_resource, native_member_for_path
from .base import BaseStorageDriveNormalizer


class HPEStorageDriveNormalizer(BaseStorageDriveNormalizer):
    """Normalize an HPE SmartStorage DiskDrive as a Redfish Drive."""

    def prefetch(self, ctx: NormalizationContext) -> None:
        ctx.prefetched["native"] = native_member_for_path(ctx.client, ctx.odata_id)

    def normalized_body_from_prefetch(
        self,
        ctx: NormalizationContext,
    ) -> Optional[Dict[str, Any]]:
        return build_drive_resource(
            ctx.odata_id, ctx.data, native=ctx.prefetched.get("native")
        )
