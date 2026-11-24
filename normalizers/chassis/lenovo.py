# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo Chassis: marketing ``ProductName`` vs MTM ``Model`` / ``SKU``.

ThinkSystem XCC often sets top-level ``Model`` to the machine type / MTM string
(e.g. ``7DHECTO1WW``) while the human-readable name lives in
``Oem.Lenovo.ProductName``. Clients that only read ``Model`` (e.g. chassis info
metrics) then show MTM as the *model* label.

We set normalized ``Model`` from ``ProductName`` when present, and keep both
identifiers on ``SKU``: Redfish ``SKU`` and the original ``Model`` (MTM) are
joined with ``|`` when both are non-empty and differ; otherwise whichever is set.

``Oem.Lenovo.FruPartNumber`` is copied into ``Oem.Redpool.FruPartNumber`` for
collectors that emit ``fru_part_number``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

from .._shared.lenovo_system_board import strip_lenovo_system_board_suffix
from ..types import NormalizationContext
from .base import BaseChassisNormalizer


def _strip_str(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _lenovo_product_name(data: Dict[str, Any]) -> str:
    oem = data.get("Oem")
    if not isinstance(oem, dict):
        return ""
    lnv = oem.get("Lenovo")
    if not isinstance(lnv, dict):
        return ""
    return _strip_str(lnv.get("ProductName"))


def effective_lenovo_chassis_model(ctx: NormalizationContext) -> Any:
    pn = _lenovo_product_name(ctx.data)
    if pn:
        return strip_lenovo_system_board_suffix(pn)
    return strip_lenovo_system_board_suffix(ctx.data.get("Model"))


def effective_lenovo_chassis_sku(ctx: NormalizationContext) -> Any:
    pn = _lenovo_product_name(ctx.data)
    if not pn:
        return ctx.data.get("SKU")

    raw_m = _strip_str(ctx.data.get("Model"))
    raw_s = _strip_str(ctx.data.get("SKU"))
    if raw_s and raw_m and raw_s != raw_m:
        return f"{raw_s}|{raw_m}"
    if raw_m:
        return raw_m
    if raw_s:
        return raw_s
    return ctx.data.get("SKU")


def _lenovo_chassis_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    rp: Dict[str, Any] = {}
    existing = out.get("Redpool")
    if isinstance(existing, dict):
        rp = copy.deepcopy(existing)
    lnv = out.get("Lenovo")
    if isinstance(lnv, dict):
        fru = lnv.get("FruPartNumber")
        if isinstance(fru, str) and fru.strip():
            rp["FruPartNumber"] = fru.strip()
    if rp:
        out["Redpool"] = rp
    else:
        out.pop("Redpool", None)
    return out


class LenovoChassisNormalizer(BaseChassisNormalizer):
    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Model"] = effective_lenovo_chassis_model
        m["SKU"] = effective_lenovo_chassis_sku
        m["Oem"] = _lenovo_chassis_oem
        return m
