# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE-specific processor normalizer."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ...types import NormalizationContext
from .base import BaseProcessorNormalizer, resolve_base_speed


class HPEProcessorNormalizer(BaseProcessorNormalizer):
    _DIMM_PATTERNS = {
        "1": re.compile(r"proc1dimm\d+$"),
        "2": re.compile(r"proc2dimm\d+$"),
    }

    def memory_dimm_pattern(self, ctx: NormalizationContext) -> Optional[re.Pattern]:
        return self._DIMM_PATTERNS.get(ctx.data.get("Id"))

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["BaseSpeedMHz"] = lambda ctx: resolve_base_speed(
            ctx, (("Hpe", "RatedSpeedMHz"),)
        )
        return m

    def version_overrides(self) -> Dict[str, Dict[str, Any]]:
        return {
            "#Processor.v1_7_2.Processor": {
                "BaseSpeedMHz": lambda ctx: (
                    ctx.data.get("Oem", {}).get("Hpe", {}).get("RatedSpeedMHz")
                    if (not ctx.config or ctx.config.use_vendor_oem_overrides)
                    else ctx.data.get("BaseSpeedMHz")
                ),
                "TotalEnabledCores": lambda ctx: (
                    ctx.data.get("Oem", {}).get("Hpe", {}).get("CoresEnabled")
                    if (not ctx.config or ctx.config.use_vendor_oem_overrides)
                    else ctx.data.get("TotalEnabledCores")
                ),
            },
        }
