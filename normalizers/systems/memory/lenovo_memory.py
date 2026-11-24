# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo Memory: Oem.Lenovo fields into ``Oem.Redpool``."""

from __future__ import annotations

from typing import Any, Dict

from ...optional import omit_if_null
from ...types import NormalizationContext
from .base import (
    BaseMemoryNormalizer,
    memory_oem,
)
from .lenovo import (
    extend_redpool_from_lenovo_oem,
    lenovo_bmc_to_canonical_memory_location,
)
from .memory_location import generate_memory_location, model_fold


def _extend(rp: Dict[str, Any], oem: Dict[str, Any], ctx: NormalizationContext) -> None:
    lenovo = oem.get("Lenovo")
    if isinstance(lenovo, dict):
        extend_redpool_from_lenovo_oem(rp, lenovo)


def _lenovo_memory_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    return memory_oem(ctx, _extend)


def _canonical_location(ctx: NormalizationContext, quad: Any) -> Any:
    return lenovo_bmc_to_canonical_memory_location(model_fold(ctx.model), *quad) or quad


def _lenovo_memory_location(ctx: NormalizationContext) -> Any:
    return generate_memory_location(ctx, canonical=_canonical_location)


class LenovoMemoryNormalizer(BaseMemoryNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["Oem"] = _lenovo_memory_oem
        mapping["MemoryLocation"] = omit_if_null(_lenovo_memory_location)
        return mapping
