# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Supermicro Power: propagate member Critical health into Redundancy.Status."""

from __future__ import annotations

from typing import Any, Dict, List

from ...types import NormalizationContext
from .base import BasePowerNormalizer, normalize_power_supplies


def _worst_health(*vals: Any) -> str:
    order = {"Critical": 3, "Warning": 2, "OK": 1, "Unknown": 0}
    best = "OK"
    best_n = -1
    for v in vals:
        if not isinstance(v, str) or not v.strip():
            continue
        n = order.get(v.strip(), 0)
        if n > best_n:
            best_n = n
            best = v.strip()
    return best if best_n >= 0 else "OK"


def _normalize_redundancy_supermicro(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    """If any RedundancySet PSU is Critical/Warning, raise Redundancy.Status.Health."""
    raw = ctx.data.get("Redundancy") or []
    if not isinstance(raw, list):
        return []
    supplies = ctx.data.get("PowerSupplies") or []
    by_index: Dict[str, Dict[str, Any]] = {}
    if isinstance(supplies, list):
        for i, s in enumerate(supplies):
            if isinstance(s, dict):
                by_index[str(i)] = s
                mid = s.get("MemberId")
                if mid is not None:
                    by_index[str(mid)] = s

    out: List[Dict[str, Any]] = []
    for red in raw:
        if not isinstance(red, dict):
            continue
        item = dict(red)
        member_healths: List[str] = []
        rset = item.get("RedundancySet") or []
        if isinstance(rset, list):
            for link in rset:
                if not isinstance(link, dict):
                    continue
                oid = link.get("@odata.id") or ""
                # Fragments like .../Power#/PowerSupplies/0
                idx = ""
                if "PowerSupplies/" in oid:
                    idx = oid.rsplit("PowerSupplies/", 1)[-1].split("/")[0]
                ps = by_index.get(idx)
                if isinstance(ps, dict):
                    st = ps.get("Status") or {}
                    if isinstance(st, dict) and st.get("Health"):
                        member_healths.append(str(st.get("Health")))
        if member_healths:
            worst = _worst_health(*member_healths)
            st = (
                dict(item.get("Status") or {})
                if isinstance(item.get("Status"), dict)
                else {}
            )
            cur = st.get("Health")
            if worst in ("Critical", "Warning") and (
                not cur or cur == "OK" or cur == "Unknown"
            ):
                st["Health"] = worst
                item["Status"] = st
        out.append(item)
    return out


def _supermicro_power_supplies(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    """``SensorNumber`` is not a PowerSupply property. Keep it under ``Oem.Redpool``."""
    supplies = normalize_power_supplies(ctx)
    for item in supplies:
        if "SensorNumber" not in item:
            continue
        number = item.pop("SensorNumber")
        oem = item.get("Oem")
        oem = dict(oem) if isinstance(oem, dict) else {}
        redpool = oem.get("Redpool")
        block = dict(redpool) if isinstance(redpool, dict) else {}
        block["SensorNumber"] = number
        oem["Redpool"] = block
        item["Oem"] = oem
    return supplies


class SupermicroPowerNormalizer(BasePowerNormalizer):
    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["PowerSupplies"] = _supermicro_power_supplies
        m["Redundancy"] = _normalize_redundancy_supermicro
        return m
