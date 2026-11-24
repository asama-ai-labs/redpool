# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE chassis PCIeDevice identity from the request path."""

from __future__ import annotations

from typing import Any, Dict

from ...identity import id_or_leaf, name_or_leaf, odata_id_or_path
from .base import BasePCIeDeviceNormalizer


class HPEChassisPCIeDeviceNormalizer(BasePCIeDeviceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["@odata.id"] = odata_id_or_path
        mapping["Id"] = id_or_leaf
        mapping["Name"] = name_or_leaf
        return mapping
