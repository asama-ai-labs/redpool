# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE PowerSupply: HotPluggable from Oem.Hpe when the standard property is absent."""

from __future__ import annotations

from typing import Any, Dict

from ...types import NormalizationContext
from ..power.hpe import hot_pluggable_from_hpe_oem
from .base import BasePowerSupplyNormalizer


def _hot_pluggable(ctx: NormalizationContext) -> Any:
    hot = hot_pluggable_from_hpe_oem(ctx.data)
    return hot if hot is not None else ctx.data.get("HotPluggable")


class HPEPowerSupplyNormalizer(BasePowerSupplyNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["HotPluggable"] = _hot_pluggable
        return mapping
