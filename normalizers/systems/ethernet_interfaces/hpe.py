# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE system EthernetInterface identity from the request path."""

from __future__ import annotations

from typing import Any, Dict

from ..._shared.live_links import (
    live_members,
    live_members_count,
    prefetch_live_members,
)
from ...collection_members import hpe_blank_members_as_links
from ...identity import id_or_leaf, name_or_leaf, odata_id_or_path
from ...types import NormalizationContext
from .base import COLLECTION_MAPPING, BaseEthernetInterfaceNormalizer
from .dell import effective_ethernet_name


# iLO lists interfaces it then cannot serve; the collector fails the whole collection on one.
HPE_COLLECTION_MAPPING: Dict[str, Any] = {
    **COLLECTION_MAPPING,
    "Members": live_members(hpe_blank_members_as_links),
    "Members@odata.count": live_members_count,
}
hpe_collection_prefetch = prefetch_live_members(hpe_blank_members_as_links)


def _hpe_ethernet_name(ctx: NormalizationContext) -> Any:
    name = effective_ethernet_name(ctx)
    if isinstance(name, str) and name.strip():
        return name
    return name_or_leaf(ctx)


class HPESystemEthernetInterfaceNormalizer(BaseEthernetInterfaceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["@odata.id"] = odata_id_or_path
        mapping["Id"] = id_or_leaf
        mapping["Name"] = _hpe_ethernet_name
        return mapping
