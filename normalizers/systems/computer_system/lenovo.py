# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo-specific ComputerSystem normalizer.

Lenovo BMCs often report Model with a trailing \" System Board\" (e.g.
\"ThinkSystem SR675 V3 System Board\"). Strip that suffix for a cleaner
product model string aligned with chassis/SKU naming.
"""

from __future__ import annotations

from typing import Any, Dict

from ..._shared.lenovo_system_board import strip_lenovo_system_board_suffix
from ...types import NormalizationContext
from .base import BaseComputerSystemNormalizer


def _lenovo_model(ctx: NormalizationContext) -> Any:
    return strip_lenovo_system_board_suffix(ctx.data.get("Model"))


class LenovoComputerSystemNormalizer(BaseComputerSystemNormalizer):
    """Strip trailing ' System Board' from Model on Lenovo systems."""

    def field_map(self) -> Dict[str, Any]:
        base = super().field_map()
        return {**base, "Model": _lenovo_model}
