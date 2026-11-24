# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Intel Storage: drop ``Drives`` entries the BMC answers with an error.

An Intel M50 lists ``Storage/1/Drives/0`` and ``/1`` but returns 404 for both.
"""

from __future__ import annotations

from typing import Any, Dict

from ..._shared.live_links import live_link_items
from ...optional import omit_if_null
from ...types import NormalizationContext
from .base import BaseStorageNormalizer

_LIVE_DRIVES_KEY = "live_drives"


def _live_drives(ctx: NormalizationContext) -> Any:
    live = ctx.prefetched.get(_LIVE_DRIVES_KEY) if ctx.prefetched else None
    return ctx.data.get("Drives", []) if live is None else live


def _live_drives_count(ctx: NormalizationContext) -> Any:
    if "Drives@odata.count" not in ctx.data:
        return None
    return len(_live_drives(ctx))


class IntelStorageNormalizer(BaseStorageNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        ctx.prefetched.pop(_LIVE_DRIVES_KEY, None)
        live = live_link_items(ctx, ctx.data.get("Drives"))
        if live is not None:
            ctx.prefetched[_LIVE_DRIVES_KEY] = live

    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["Drives"] = _live_drives
        mapping["Drives@odata.count"] = omit_if_null(_live_drives_count)
        return mapping
