# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo FirmwareInventory normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ..base import ResourceNormalizer
from ..types import NormalizationContext
from ._shared.firmware_inventory import build_sparse_software_inventory


class LenovoFirmwareInventoryNormalizer(ResourceNormalizer):
    """Lenovo XCC FirmwareInventory → SoftwareInventory v1_10_2."""

    def normalized_body_from_prefetch(self, ctx: NormalizationContext):
        return build_sparse_software_inventory(ctx)

    def field_map(self) -> Dict[str, Any]:
        return {}
