# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE LogEntry OEM promotions (IML, IEL, SL, etc.)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..redfish_dates import date_time_or_none
from .base import BaseLogEntryNormalizer
from .v161 import oem_branch_to_redpool_props, severity_hpe_to_redfish


class HPELogEntryNormalizer(BaseLogEntryNormalizer):
    def apply_oem_branch(
        self,
        key: str,
        branch: Dict[str, Any],
        out: Dict[str, Any],
        redpool: Dict[str, Any],
    ) -> None:
        if key != "Hpe":
            super().apply_oem_branch(key, branch, out, redpool)
            return
        upd = date_time_or_none(branch.get("Updated"))
        if upd and not out.get("Modified"):
            out["Modified"] = upd
        rec = branch.get("RecommendedAction")
        if rec and not out.get("Resolution"):
            out["Resolution"] = rec
        if branch.get("Repaired") is True:
            out["Resolved"] = True
        mapped: Optional[str] = severity_hpe_to_redfish(branch.get("Severity"))
        if mapped:
            out["Severity"] = mapped
        redpool.update(oem_branch_to_redpool_props(branch))
