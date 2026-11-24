# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Intel Chassis: drop ``Links.Contains`` entries the BMC answers with an error.

An Intel M50 lists ``Chassis/RackMount/AICCardFRU1`` in ``Contains`` but returns 404 for it.
"""

from __future__ import annotations

from typing import Any, Dict

from .._shared.live_links import live_link_items
from ..types import NormalizationContext
from .base import BaseChassisNormalizer

_LIVE_CONTAINS_KEY = "live_contains"


def prefetch_live_contains(ctx: NormalizationContext) -> None:
    ctx.prefetched.pop(_LIVE_CONTAINS_KEY, None)
    links = ctx.data.get("Links")
    live = live_link_items(
        ctx, links.get("Contains") if isinstance(links, dict) else None
    )
    if live is not None:
        ctx.prefetched[_LIVE_CONTAINS_KEY] = live


def _links_with_live_contains(ctx: NormalizationContext) -> Any:
    links = ctx.data.get("Links", {})
    live = ctx.prefetched.get(_LIVE_CONTAINS_KEY) if ctx.prefetched else None
    if not isinstance(links, dict) or live is None:
        return links
    out = dict(links)
    out["Contains"] = live
    if "Contains@odata.count" in out:
        out["Contains@odata.count"] = len(live)
    return out


class IntelChassisNormalizer(BaseChassisNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        super().prefetch(ctx)
        prefetch_live_contains(ctx)

    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["Links"] = _links_with_live_contains
        return mapping
