# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell-specific processor normalizer."""

from __future__ import annotations

import re
from typing import Optional

from ...types import NormalizationContext
from .base import BaseProcessorNormalizer


class DellProcessorNormalizer(BaseProcessorNormalizer):
    _DIMM_PATTERNS = {
        "CPU.Socket.1": re.compile(r"A\d+$"),
        "CPU.Socket.2": re.compile(r"B\d+$"),
    }

    def memory_dimm_pattern(self, ctx: NormalizationContext) -> Optional[re.Pattern]:
        return self._DIMM_PATTERNS.get(ctx.data.get("Id"))
