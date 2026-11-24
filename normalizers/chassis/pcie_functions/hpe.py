# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE chassis PCIeFunction identity from the request path."""

from __future__ import annotations

from typing import Any, Dict

from ...identity import id_or_leaf, name_or_leaf, odata_id_or_path
from ...pcie_display import pcie_function_display_name
from ...types import NormalizationContext
from .base import BasePCIeFunctionNormalizer, normalize_name


def _hpe_function_name(ctx: NormalizationContext) -> Any:
    name = pcie_function_display_name(ctx, normalize_name)
    if isinstance(name, str) and name.strip():
        return name
    return name_or_leaf(ctx)


class HPEChassisPCIeFunctionNormalizer(BasePCIeFunctionNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["@odata.id"] = odata_id_or_path
        mapping["Id"] = id_or_leaf
        mapping["Name"] = _hpe_function_name
        return mapping
