# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Drop link entries the BMC answers with an error.

Some BMCs list a resource they then return 404 for. A client that follows every link,
as gofish and fishymetrics do, fails the whole tree on it. Prefetch only: the GETs go
through the cached client, so the client's own request for each live entry is a cache hit.
"""

from __future__ import annotations

from typing import Any, Callable, List

from redpool.redfish_client import redfish_get_json

from ..optional import OMIT
from ..types import NormalizationContext


def _odata_id(ref: Any) -> str:
    if isinstance(ref, dict):
        oid = ref.get("@odata.id")
        if isinstance(oid, str) and oid.strip():
            return oid.strip().split("#")[0]
    return ""


def live_link_items(ctx: NormalizationContext, items: Any) -> List[Any] | None:
    """Return *items* without the entries whose resource the BMC cannot serve.

    ``None`` when *items* is not a list or there is no client, so callers leave the field alone.
    """
    if ctx.client is None or not isinstance(items, list):
        return None
    live: List[Any] = []
    for item in items:
        uri = _odata_id(item)
        if uri and not redfish_get_json(ctx.client, uri):
            continue
        live.append(item)
    return live


LIVE_MEMBERS_KEY = "live_members"


def prefetch_live_members(
    members_of: Callable[[NormalizationContext], Any],
) -> Callable[[NormalizationContext], None]:
    """A collection prefetch that keeps the ``Members`` the BMC can serve.

    *members_of* returns the member list to check, so a vendor can repair it first.
    """

    def _prefetch(ctx: NormalizationContext) -> None:
        ctx.prefetched.pop(LIVE_MEMBERS_KEY, None)
        live = live_link_items(ctx, members_of(ctx))
        if live is not None:
            ctx.prefetched[LIVE_MEMBERS_KEY] = live

    return _prefetch


def live_members(
    members_of: Callable[[NormalizationContext], Any],
) -> Callable[[NormalizationContext], Any]:
    """Collection ``Members``: the prefetched live ones, else *members_of* unchanged."""

    def _members(ctx: NormalizationContext) -> Any:
        live = ctx.prefetched.get(LIVE_MEMBERS_KEY) if ctx.prefetched else None
        return members_of(ctx) if live is None else live

    return _members


def live_members_count(ctx: NormalizationContext) -> Any:
    """``Members@odata.count`` follows the live list; omitted when the BMC sent none."""
    if "Members@odata.count" not in ctx.data:
        return OMIT
    live = ctx.prefetched.get(LIVE_MEMBERS_KEY) if ctx.prefetched else None
    count = ctx.data.get("Members@odata.count")
    return count if live is None else len(live)
