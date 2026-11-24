# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Intel Memory identity from the request path."""

from __future__ import annotations

from typing import Any, Dict

from ...identity import id_or_leaf, name_or_leaf, odata_id_or_path
from ...optional import omit_if_null
from ...types import NormalizationContext
from .base import BaseMemoryNormalizer
from .memory_location import dec1, generate_memory_location


def _canonical_location(ctx: NormalizationContext, quad: Any) -> Any:
    socket, memory_controller, channel, slot = quad
    return (socket, memory_controller, channel, dec1(slot))


def _intel_memory_location(ctx: NormalizationContext) -> Any:
    return generate_memory_location(ctx, canonical=_canonical_location)


class IntelMemoryNormalizer(BaseMemoryNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["@odata.id"] = odata_id_or_path
        mapping["Id"] = id_or_leaf
        mapping["Name"] = name_or_leaf
        mapping["MemoryLocation"] = omit_if_null(_intel_memory_location)
        return mapping
