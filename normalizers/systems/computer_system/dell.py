# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell ComputerSystem: promote DellSystem rollup health into Oem.Redpool."""

from __future__ import annotations

import copy
from typing import Any, Dict

from ...service_root import register_bmc_product_marker
from ...types import NormalizationContext
from .base import BaseComputerSystemNormalizer

# Dell publishes "Integrated Dell Remote Access Controller" as ServiceRoot.Product on every
# PowerEdge. That is the iDRAC's name, not the platform's.
register_bmc_product_marker("remote access controller")

# Explicit high-value rollups plus any other *RollupStatus string on DellSystem.
_ROLLUP_KEYS = (
    "SystemHealthRollupStatus",
    "CPURollupStatus",
    "FanRollupStatus",
    "PSRollupStatus",
    "SELRollupStatus",
    "CoolingRollupStatus",
    "BatteryRollupStatus",
    "IntrusionRollupStatus",
    "MemoryRollupStatus",
    "StorageRollupStatus",
    "TempRollupStatus",
    "VoltRollupStatus",
)

_NUMERIC_KEYS = (
    "EstimatedSystemAirflowCFM",
    "EstimatedExhaustTemperatureCelsius",
)


def _dell_system_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    rp: Dict[str, Any] = {}
    existing = out.get("Redpool")
    if isinstance(existing, dict):
        rp = copy.deepcopy(existing)
    dell = out.get("Dell")
    if isinstance(dell, dict):
        ds = dell.get("DellSystem")
        if isinstance(ds, dict):
            for key in _ROLLUP_KEYS:
                val = ds.get(key)
                if isinstance(val, str) and val.strip():
                    rp[key] = val.strip()
            # Catch any additional *RollupStatus the BMC adds in newer iDRAC.
            for key, val in ds.items():
                if (
                    isinstance(key, str)
                    and key.endswith("RollupStatus")
                    and key not in rp
                    and isinstance(val, str)
                    and val.strip()
                ):
                    rp[key] = val.strip()
            for key in _NUMERIC_KEYS:
                val = ds.get(key)
                if isinstance(val, (int, float)):
                    rp[key] = val
            for key in (
                "NodeID",
                "ChassisServiceTag",
                "ExpressServiceCode",
                "PlatformGUID",
            ):
                val = ds.get(key)
                if val is not None and str(val).strip():
                    rp[key] = str(val).strip()
    if rp:
        out["Redpool"] = rp
    else:
        out.pop("Redpool", None)
    return out


class DellComputerSystemNormalizer(BaseComputerSystemNormalizer):
    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Oem"] = _dell_system_oem
        return m
