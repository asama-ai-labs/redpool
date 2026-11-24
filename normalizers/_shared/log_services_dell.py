# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell LogEntry collection: complete the Lclog members, then the shared member handling."""

from __future__ import annotations

import dataclasses
from typing import Any, Dict

from .log_entry.dell import complete_dell_lclog_member
from .log_services import LOG_ENTRY_COLLECTION, log_entry_collection_members


def _dell_log_entry_collection_members(ctx: Any) -> Any:
    members = ctx.data.get("Members")
    if isinstance(members, list):
        collection_id = ctx.data.get("@odata.id") or ctx.odata_id or ""
        members = [
            complete_dell_lclog_member(m, collection_id) if isinstance(m, dict) else m
            for m in members
        ]
        ctx = dataclasses.replace(ctx, data={**ctx.data, "Members": members})
    return log_entry_collection_members(ctx)


DELL_LOG_ENTRY_COLLECTION: Dict[str, Any] = {
    **LOG_ENTRY_COLLECTION,
    "Members": _dell_log_entry_collection_members,
}
