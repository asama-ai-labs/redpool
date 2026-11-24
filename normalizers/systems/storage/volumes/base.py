# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Volume normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ....base import ResourceNormalizer
from ....optional import optional
from ....types import NormalizationContext


def volume_links(ctx: NormalizationContext) -> dict:
    """Keep drive membership on ``Links.Drives``.

    Volume has no top-level ``Drives``. A payload that still carries one is
    appended to ``Links.Drives`` without repeating an existing ``@odata.id``.
    """
    raw = ctx.data.get("Links")
    links = dict(raw) if isinstance(raw, dict) else {}
    incoming = ctx.data.get("Drives")
    if not isinstance(incoming, list) or not incoming:
        return links
    existing = links.get("Drives")
    merged = list(existing) if isinstance(existing, list) else []
    seen = {
        item.get("@odata.id")
        for item in merged
        if isinstance(item, dict) and isinstance(item.get("@odata.id"), str)
    }
    added = False
    for item in incoming:
        if isinstance(item, dict) and isinstance(item.get("@odata.id"), str):
            if item["@odata.id"] in seen:
                continue
            seen.add(item["@odata.id"])
        elif item in merged:
            continue
        merged.append(item)
        added = True
    if not added:
        return links
    links["Drives"] = merged
    links["Drives@odata.count"] = len(merged)
    return links


class BaseVolumeNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Volume.Volume",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Volume.v1_10_0.Volume",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "CapacityBytes": optional("CapacityBytes"),
            "VolumeType": optional("VolumeType"),
            "Encrypted": optional("Encrypted"),
            "EncryptionTypes": lambda ctx: ctx.data.get("EncryptionTypes", []),
            "RAIDType": optional("RAIDType"),
            "OptimumIOSizeBytes": optional("OptimumIOSizeBytes"),
            "StripSizeBytes": optional("StripSizeBytes"),
            "BlockSizeBytes": optional("BlockSizeBytes"),
            "MediaSpanCount": optional("MediaSpanCount"),
            "ReadCachePolicy": optional("ReadCachePolicy"),
            "WriteCachePolicy": optional("WriteCachePolicy"),
            "DisplayName": optional("DisplayName"),
            "Identifiers": lambda ctx: ctx.data.get("Identifiers", []),
            "Links": volume_links,
            "Operations": lambda ctx: ctx.data.get("Operations", []),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


def collection_member_links(ctx: NormalizationContext) -> list:
    """Members of a collection are bare links; drop keys a BMC adds beside ``@odata.id``."""
    members = ctx.data.get("Members")
    if not isinstance(members, list):
        return []
    return [
        {"@odata.id": member["@odata.id"]}
        for member in members
        if isinstance(member, dict) and member.get("@odata.id")
    ]


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#VolumeCollection.VolumeCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#VolumeCollection.VolumeCollection",
    "Members": collection_member_links,
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Volumes",
    "Name": "VolumeCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
