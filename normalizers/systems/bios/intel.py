# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Intel Bios: keep vendor ``Oem`` and copy the password-bypass flag to ``Oem.Redpool``."""

from __future__ import annotations

import copy
from typing import Any, Dict

from ...identity import id_or_leaf, name_or_leaf, odata_id_or_path
from ...types import NormalizationContext
from .base import BaseBiosNormalizer


def _intel_bios_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    oem = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(oem) if isinstance(oem, dict) else {}
    if "BypassBIOSPwFlag" not in out:
        return out
    redpool = out.get("Redpool")
    rp: Dict[str, Any] = dict(redpool) if isinstance(redpool, dict) else {}
    rp["BypassBIOSPwFlag"] = out.pop("BypassBIOSPwFlag")
    out["Redpool"] = rp
    return out


class IntelBiosNormalizer(BaseBiosNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["@odata.id"] = odata_id_or_path
        mapping["Id"] = id_or_leaf
        mapping["Name"] = name_or_leaf
        mapping["Oem"] = _intel_bios_oem
        return mapping
