# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE iLO FirmwareInventory normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ..base import ResourceNormalizer
from ..types import NormalizationContext
from ._shared.firmware_inventory import (
    VendorFirmwareLabels,
    build_sparse_software_inventory,
)


def _hpe_before_related(ctx: NormalizationContext, rp: Dict[str, Any]) -> None:
    oem = ctx.data.get("Oem")
    hpe_oem = oem.get("Hpe") if isinstance(oem, dict) else None
    if isinstance(hpe_oem, dict):
        ctx_dev = hpe_oem.get("DeviceContext")
        if isinstance(ctx_dev, str) and ctx_dev.strip():
            rp["device_context"] = ctx_dev.strip()


HPE_FIRMWARE_LABELS = VendorFirmwareLabels(before_related=_hpe_before_related)


class HPEFirmwareInventoryNormalizer(ResourceNormalizer):
    """HPE FirmwareInventory → SoftwareInventory v1_10_2."""

    def normalized_body_from_prefetch(self, ctx: NormalizationContext):
        body = build_sparse_software_inventory(ctx, HPE_FIRMWARE_LABELS)
        name = body.get("Name")
        if not isinstance(name, str) or not name.strip():
            item_id = body.get("Id")
            if isinstance(item_id, str) and item_id.strip():
                body["Name"] = item_id.strip()
        return body

    def field_map(self) -> Dict[str, Any]:
        return {}
