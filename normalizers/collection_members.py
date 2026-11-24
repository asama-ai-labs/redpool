# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Collection members that are not full resources."""

from __future__ import annotations

from typing import Any

from .optional import OMIT
from .types import NormalizationContext


def hpe_blank_members_as_links(ctx: NormalizationContext) -> Any:
    """HPE collections that send ``Id`` with an empty ``@odata.id`` become idRefs.

    Register it only in an HPE collection override.
    """
    members = ctx.data.get("Members")
    if members is None:
        return OMIT
    if not isinstance(members, list):
        return members
    raw_id = ctx.data.get("@odata.id")
    if isinstance(raw_id, str) and raw_id.strip():
        base = raw_id.strip().rstrip("/")
    else:
        base = (ctx.resource_path or "").rstrip("/")
    out = []
    for member in members:
        if not isinstance(member, dict):
            out.append(member)
            continue
        oid = member.get("@odata.id")
        if isinstance(oid, str) and oid.strip():
            out.append(member)
            continue
        member_id = member.get("Id")
        if base and member_id not in (None, ""):
            out.append({"@odata.id": f"{base}/{member_id}"})
        else:
            out.append(member)
    return out
