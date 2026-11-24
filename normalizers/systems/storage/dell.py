# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell Storage: promote DellControllerBattery into Oem.Redpool for generic collectors."""

from __future__ import annotations

import copy
from typing import Any, Dict

from ...types import NormalizationContext
from .base import BaseStorageNormalizer
from .controllers.dell import dell_controller_battery


def _dell_storage_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    battery = dell_controller_battery(ctx.data)
    if not battery:
        return out
    rp = out.get("Redpool")
    if not isinstance(rp, dict):
        rp = {}
    else:
        rp = copy.deepcopy(rp)
    rp["ControllerBattery"] = {
        "Id": battery.get("Id") or battery.get("FQDD") or "1",
        "Name": battery.get("Name"),
        "PrimaryStatus": battery.get("PrimaryStatus"),
        "RAIDState": battery.get("RAIDState"),
        "FQDD": battery.get("FQDD"),
    }
    out["Redpool"] = rp
    return out


class DellStorageNormalizer(BaseStorageNormalizer):
    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Oem"] = _dell_storage_oem
        return m
