# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell-specific Power normalizer.

Dell Power (e.g. PowerEdge R630) often omits PowerCapacityWatts on each PSU
and instead provides InputRanges[].OutputWattage. This normalizer derives
PowerCapacityWatts from InputRanges[0].OutputWattage when PowerCapacityWatts
is missing or zero; fallback: parse "NNNW" from Model (e.g. "750W").

**Manufacture date** — On newer iDRAC, each PSU ``Assembly`` includes
``Assemblies[0].ProductionDate`` (ISO 8601). Prefetch reads those resources
and copies week / year / calendar date into ``Oem.Redpool`` on each embedded
``PowerSupply``, matching :func:`normalizers.systems.memory.dell.extend_redpool_from_dell_oem`
field names (``ManufactureWeek``, ``ManufactureYear``, ``ManufactureDate``).
Older models without ``Assembly`` on PSUs are unchanged.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

from redpool.redfish_client import redfish_get_json

from ...types import NormalizationContext
from ..._shared.dell_assembly_fru import (
    assembly_odata_path,
    parse_dell_assembly_production_date,
    production_date_from_assembly_payload,
    redpool_fields_from_assembly_block,
    select_assembly_block,
)
from ...vendor_id import normalize_power_supply_manufacturer
from .base import BasePowerNormalizer, normalize_power_supplies

_DELL_PSU_ASSEMBLY_MFG_CACHE = "DellPsuAssemblyManufacture"


def merge_dell_power_supply_assembly_manufacture_into_supplies(
    supplies: List[Dict[str, Any]], ctx: NormalizationContext
) -> None:
    """Apply prefetched manufacture fields to each supply's ``Oem.Redpool``."""
    for s in supplies:
        _merge_psu_oem_redpool_manufacture(s, ctx)


def _psu_assembly_match_key(psu: Dict[str, Any]) -> Optional[str]:
    """Key used to select the matching Assemblies[] FRU for this PSU."""
    for field in ("MemberId", "MemberID", "Id", "Name"):
        val = psu.get(field)
        if isinstance(val, str) and val.strip():
            key = val.strip().split("#", 1)[0]
            if "PSU" in key.upper() or "Slot" in key:
                return key
    return None


def _prefetch_psu_assembly_manufacture_dates(ctx: NormalizationContext) -> None:
    raw = ctx.data.get("PowerSupplies") or []
    candidates: List[Any] = (
        raw
        if isinstance(raw, list) and raw
        else (ctx.prefetched or {}).get("PowerSupplies") or []
    )
    if not isinstance(candidates, list) or not candidates:
        return
    if ctx.prefetched is None:
        ctx.prefetched = {}
    # Cache keyed by assembly path + PSU match key (chassis-wide Assembly has many members).
    cache: Dict[str, Dict[str, Any]] = {}
    payload_by_path: Dict[str, Dict[str, Any]] = {}
    for psu in candidates:
        if not isinstance(psu, dict):
            continue
        asm = psu.get("Assembly")
        if not isinstance(asm, dict):
            continue
        ref = asm.get("@odata.id")
        if not isinstance(ref, str) or not ref.strip():
            continue
        path = assembly_odata_path(ref)
        match_key = _psu_assembly_match_key(psu)
        cache_key = f"{path}::{match_key or ''}"
        if cache_key in cache:
            continue
        if path not in payload_by_path:
            try:
                payload = redfish_get_json(ctx.client, path)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(payload, dict):
                continue
            payload_by_path[path] = payload
        payload = payload_by_path[path]
        entry: Dict[str, Any] = {}
        pd = production_date_from_assembly_payload(payload, match_key)
        if pd is not None:
            parsed = parse_dell_assembly_production_date(pd)
            if parsed is not None:
                wk, yr, iso_date = parsed
                entry["ManufactureWeek"] = wk
                entry["ManufactureYear"] = yr
                entry["ManufactureDate"] = iso_date
        block = select_assembly_block(payload, match_key)
        if block is not None:
            for key, val in redpool_fields_from_assembly_block(block).items():
                if key not in entry or not entry.get(key):
                    entry[key] = val
        if entry:
            cache[cache_key] = entry
    if cache:
        ctx.prefetched[_DELL_PSU_ASSEMBLY_MFG_CACHE] = cache


def _merge_psu_oem_redpool_manufacture(
    s: Dict[str, Any], ctx: NormalizationContext
) -> None:
    asm = s.get("Assembly")
    if not isinstance(asm, dict):
        return
    ref = asm.get("@odata.id")
    if not isinstance(ref, str) or not ref.strip():
        return
    path = assembly_odata_path(ref)
    match_key = _psu_assembly_match_key(s)
    cache_key = f"{path}::{match_key or ''}"
    cache = (ctx.prefetched or {}).get(_DELL_PSU_ASSEMBLY_MFG_CACHE) or {}
    mfg = cache.get(cache_key)
    if not isinstance(mfg, dict):
        # Legacy cache keyed by path only (per-PSU Assembly docs).
        mfg = cache.get(path)
    if not isinstance(mfg, dict):
        return
    oem_src = s.get("Oem")
    oem: Dict[str, Any] = copy.deepcopy(oem_src) if isinstance(oem_src, dict) else {}
    rp = oem.get("Redpool")
    if not isinstance(rp, dict):
        rp = {}
    rp2 = dict(rp)
    if "ManufactureWeek" in mfg:
        rp2["ManufactureWeek"] = mfg["ManufactureWeek"]
        rp2["ManufactureYear"] = mfg["ManufactureYear"]
        rp2["ManufactureDate"] = mfg["ManufactureDate"]
    for key in (
        "FruPartNumber",
        "EngineeringChangeLevel",
        "ManufactureWeek",
        "ManufactureYear",
        "ManufactureDate",
    ):
        if mfg.get(key) and not rp2.get(key):
            rp2[key] = mfg[key]
    oem["Redpool"] = rp2
    s["Oem"] = oem


def _derive_power_capacity_watts(item: Dict[str, Any]) -> Any:
    """Derive PowerCapacityWatts from InputRanges[0].OutputWattage or Model NNNW."""
    val = item.get("PowerCapacityWatts")
    if val is not None and val != 0:
        return val
    ranges = item.get("InputRanges") or item.get("inputRanges")
    if isinstance(ranges, list) and len(ranges) > 0:
        first = ranges[0]
        if isinstance(first, dict):
            w = first.get("OutputWattage") or first.get("outputWattage")
            if w is not None and w != 0:
                return int(w) if isinstance(w, float) and w == int(w) else w
    model = item.get("Model") or item.get("model") or ""
    if isinstance(model, str):
        match = re.search(r"(\d+)\s*W\b", model, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _dell_psu_odm_tail_from_model(model: Any) -> Optional[str]:
    """Last comma-separated segment of iDRAC ``Model`` (e.g. ``...,DELTA``, ``...,LTON``)."""
    if not isinstance(model, str):
        return None
    parts = [p.strip() for p in model.split(",") if p.strip()]
    if not parts:
        return None
    return parts[-1]


def _is_dell_only_psu_branding(mfg: Any) -> bool:
    if not isinstance(mfg, str):
        return False
    t = mfg.strip().casefold()
    return t == "dell" or t in ("dell inc", "dell inc.")


def _normalize_psu_name_dell(item: Dict[str, Any]) -> str | None:
    """Return a cleaner PSU name: strip ' Status' from Name, or derive from MemberId (e.g. PSU.Slot.1 → PS1)."""
    name = (item.get("Name") or "").strip()
    if name.endswith(" Status"):
        return name[:-7].strip() or None  # "PS1 Status" → "PS1"
    member_id = (item.get("MemberId") or item.get("MemberID") or "").strip()
    if member_id and not name:
        # PSU.Slot.1 → PS1, PSU.Slot.2 → PS2
        if ".Slot." in member_id:
            try:
                slot = member_id.split(".Slot.")[-1]
                return f"PS{slot}"
            except Exception:  # noqa: S110
                pass
        return f"PSU {member_id}"
    return name or None


def _normalize_power_supplies_dell(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    """Same as base normalize_power_supplies, then set PowerCapacityWatts and Name from Dell sources."""
    supplies = normalize_power_supplies(ctx)
    merge_dell_power_supply_assembly_manufacture_into_supplies(supplies, ctx)
    for s in supplies:
        derived = _derive_power_capacity_watts(s)
        if derived is not None:
            s["PowerCapacityWatts"] = derived
        name = _normalize_psu_name_dell(s)
        if name is not None:
            s["Name"] = name
        mfg = s.get("Manufacturer")
        if _is_dell_only_psu_branding(mfg):
            odm = _dell_psu_odm_tail_from_model(s.get("Model"))
            if odm and odm.strip().casefold() != "dell":
                s["Manufacturer"] = normalize_power_supply_manufacturer(odm.strip())
    return supplies


class DellPowerNormalizer(BasePowerNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        super().prefetch(ctx)
        # iDRAC PSU Assembly ProductionDate → Oem.Redpool (merged in field_map).
        _prefetch_psu_assembly_manufacture_dates(ctx)

    def field_map(self) -> Dict[str, Any]:
        base_map = super().field_map()
        base_map["PowerSupplies"] = _normalize_power_supplies_dell
        return base_map
