# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Supermicro FirmwareInventory normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ..base import ResourceNormalizer
from ..types import NormalizationContext
from ._shared.firmware_inventory import (
    VendorFirmwareLabels,
    build_sparse_software_inventory,
)


def _supermicro_before_related(ctx: NormalizationContext, rp: Dict[str, Any]) -> None:
    oem = ctx.data.get("Oem")
    smc_oem = oem.get("Supermicro") if isinstance(oem, dict) else None
    if isinstance(smc_oem, dict):
        uf = smc_oem.get("UniqueFilename")
        if isinstance(uf, str) and uf.strip():
            rp["unique_filename"] = uf.strip()


SUPERMICRO_FIRMWARE_LABELS = VendorFirmwareLabels(
    before_related=_supermicro_before_related
)


class SupermicroFirmwareInventoryNormalizer(ResourceNormalizer):
    """Supermicro FirmwareInventory → SoftwareInventory v1_10_2."""

    def normalized_body_from_prefetch(self, ctx: NormalizationContext):
        return build_sparse_software_inventory(ctx, SUPERMICRO_FIRMWARE_LABELS)

    def field_map(self) -> Dict[str, Any]:
        return {}
