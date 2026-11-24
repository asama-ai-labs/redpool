# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo LogEntry OEM promotions (AuditLog, PlatformLog, etc.)."""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseLogEntryNormalizer
from .v161 import oem_branch_to_redpool_props


class LenovoLogEntryNormalizer(BaseLogEntryNormalizer):
    def apply_oem_branch(
        self,
        key: str,
        branch: Dict[str, Any],
        out: Dict[str, Any],
        redpool: Dict[str, Any],
    ) -> None:
        if key != "Lenovo":
            super().apply_oem_branch(key, branch, out, redpool)
            return
        chain = branch.get("ReportingChain")
        if chain and not out.get("Originator"):
            out["Originator"] = str(chain)
        lmsg = branch.get("LenovoMessageID")
        if lmsg and not out.get("OemLogEntryCode"):
            out["OemLogEntryCode"] = str(lmsg)
        redpool.update(oem_branch_to_redpool_props(branch))
