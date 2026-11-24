# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Intel EthernetInterface identity from the request path."""

from __future__ import annotations

from typing import Any, Dict

from ..._shared.live_links import (
    live_members,
    live_members_count,
    prefetch_live_members,
)
from ...identity import id_or_leaf, name_or_leaf, odata_id_or_path
from ...types import NormalizationContext
from .base import COLLECTION_MAPPING, BaseEthernetInterfaceNormalizer
from .dell import effective_ethernet_name


def _members(ctx: NormalizationContext) -> Any:
    return ctx.data.get("Members")


# An Intel M50 lists interfaces it then answers with 404; the collector fails the whole collection on one.
INTEL_COLLECTION_MAPPING: Dict[str, Any] = {
    **COLLECTION_MAPPING,
    "Members": live_members(_members),
    "Members@odata.count": live_members_count,
}
intel_collection_prefetch = prefetch_live_members(_members)


def ethernet_name_or_leaf(ctx: NormalizationContext) -> Any:
    name = effective_ethernet_name(ctx)
    if isinstance(name, str) and name.strip():
        return name
    return name_or_leaf(ctx)


class IntelSystemEthernetInterfaceNormalizer(BaseEthernetInterfaceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["@odata.id"] = odata_id_or_path
        mapping["Id"] = id_or_leaf
        mapping["Name"] = ethernet_name_or_leaf
        return mapping
