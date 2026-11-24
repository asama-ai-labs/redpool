# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell Chassis: promote chassis-wide Assembly FRU into ``Oem.Redpool``."""

from __future__ import annotations

import copy
from typing import Any, Dict

from .._shared.dell_assembly_fru import (
    fetch_chassis_assembly_redpool_fields,
    merge_redpool_assembly_fields,
)
from ..types import NormalizationContext
from .base import BaseChassisNormalizer

_DELL_CHASSIS_ASSEMBLY_FRU = "DellChassisAssemblyFru"


def _dell_chassis_assembly_match_keys(data: Dict[str, Any]) -> list[str]:
    keys: list[str] = []
    cid = data.get("Id")
    if isinstance(cid, str) and cid.strip():
        keys.append(cid.strip())
        if ":" in cid:
            keys.append(cid.split(":", 1)[0])
    return keys


def prefetch_dell_chassis_assembly_fru(ctx: NormalizationContext) -> None:
    if ctx.client is None:
        return
    keys = _dell_chassis_assembly_match_keys(ctx.data)
    if not keys:
        return
    fields: Dict[str, Any] = {}
    for key in keys:
        got = fetch_chassis_assembly_redpool_fields(ctx.client, ctx.odata_id, key)
        merge_redpool_assembly_fields(fields, got)
    if not fields:
        return
    if ctx.prefetched is None:
        ctx.prefetched = {}
    ctx.prefetched[_DELL_CHASSIS_ASSEMBLY_FRU] = fields


def _dell_chassis_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    rp: Dict[str, Any] = {}
    existing = out.get("Redpool")
    if isinstance(existing, dict):
        rp = copy.deepcopy(existing)
    mfg = (ctx.prefetched or {}).get(_DELL_CHASSIS_ASSEMBLY_FRU)
    if isinstance(mfg, dict):
        merge_redpool_assembly_fields(rp, mfg)
    if rp:
        out["Redpool"] = rp
    else:
        out.pop("Redpool", None)
    return out


class DellChassisNormalizer(BaseChassisNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        super().prefetch(ctx)
        prefetch_dell_chassis_assembly_fru(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Oem"] = _dell_chassis_oem
        return m
