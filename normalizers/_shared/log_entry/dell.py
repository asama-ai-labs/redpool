# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell LogEntry OEM promotions (Lclog, FaultList, etc.)."""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseLogEntryNormalizer
from .v161 import oem_branch_to_redpool_props, stamp_log_entry_type


def complete_dell_lclog_member(
    member: Dict[str, Any], collection_id: str
) -> Dict[str, Any]:
    """Dell LC collection members carry ``Id`` only. The entry document is an Oem log."""
    oid = member.get("@odata.id") if isinstance(member.get("@odata.id"), str) else ""
    if "Lclog" not in oid and "Lclog" not in (collection_id or ""):
        return member
    entry_id = member.get("Id")
    if not isinstance(entry_id, str) or not entry_id:
        return member
    if member.get("Name") and member.get("EntryType"):
        return member
    member = dict(member)
    name = member.get("Name")
    member["Name"] = name if isinstance(name, str) else ""
    member["EntryType"] = member.get("EntryType") or "Oem"
    if not member.get("@odata.type"):
        stamp_log_entry_type(member)
    return member


class DellLogEntryNormalizer(BaseLogEntryNormalizer):
    def apply_oem_branch(
        self,
        key: str,
        branch: Dict[str, Any],
        out: Dict[str, Any],
        redpool: Dict[str, Any],
    ) -> None:
        if key != "Dell":
            super().apply_oem_branch(key, branch, out, redpool)
            return
        dt = str(branch.get("@odata.type") or "")
        if "DellLogEntry" in dt:
            fqdd = branch.get("FQDD")
            if fqdd and not out.get("Description"):
                out["Description"] = fqdd
        redpool.update(oem_branch_to_redpool_props(branch))
