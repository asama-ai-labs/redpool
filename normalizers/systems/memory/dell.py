# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell PowerEdge memory: OEM manufacture dates and silk-based ``MemoryLocation``.

**Manufacture date** — iDRAC ``Oem.Dell.DellMemory.ManufactureDate`` strings (e.g.
``Mon Jul 17 ::1 2023 UTC``) are applied to ``Oem.Redpool`` via :func:`extend_redpool_from_dell_oem`
(uses :func:`parse_dell_oem_manufacture_date` for week / year / ``YYYY-MM-DD``).

On models without inline ``DellMemory`` (e.g. PowerEdge R630), :func:`prefetch_dell_memory_assembly_manufacture`
reads per-DIMM ``Assembly`` ``ProductionDate`` (chassis ``Assembly/DIMM.Socket.*`` or
``Memory/.../Assembly``) into ``ctx.prefetched`` for :func:`apply_prefetched_dell_memory_assembly_manufacture`.

**Memory location** — iDRAC does not populate numeric ``MemoryLocation`` on DIMM resources;
:func:`locator_to_location` maps ``Memory.Name`` (e.g. ``DIMM A1``) through per-model tables.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Tuple

from redpool.redfish_client import redfish_get_json

from ..._shared.dell_assembly_fru import (
    assembly_odata_path,
    parse_dell_assembly_production_date,
    production_date_from_assembly_payload,
    redpool_fields_from_assembly_block,
    select_assembly_block,
)
from ...types import NormalizationContext

_DELL_MEMORY_ASSEMBLY_MFG = "DellMemoryAssemblyManufacture"

# iDRAC often returns ``Mon Jul 17 ::1 2023 UTC`` (spurious ``::N`` segment before the year).
_DELL_MFG_DATE_NOISE = re.compile(r"\s+::\d+\s+")


def parse_dell_oem_manufacture_date(raw: str) -> Optional[Tuple[int, int, str]]:
    """Parse ``ManufactureDate`` → ``(ManufactureWeek, ManufactureYear, ManufactureDate)``.

    ``ManufactureWeek`` / ``ManufactureYear`` follow :func:`datetime.date.isocalendar`.
    ``ManufactureDate`` is ``YYYY-MM-DD`` when parsing succeeds.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if s.upper().endswith(" UTC"):
        core = s[:-4].strip()
    else:
        core = s
    core = _DELL_MFG_DATE_NOISE.sub(" ", core)
    core = re.sub(r"\s+", " ", core).strip()
    dt: Optional[datetime] = None
    for fmt in ("%a %b %d %Y", "%a %b %d %Y %H:%M:%S"):
        try:
            dt = datetime.strptime(core, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    d = dt.date()
    iso_y, iso_w, _ = d.isocalendar()
    return (int(iso_w), int(iso_y), d.isoformat())


def extend_redpool_from_dell_oem(rp: Dict[str, Any], dell: Dict[str, Any]) -> None:
    """Merge Dell OEM fields into ``Oem.Redpool`` (mutates ``rp``)."""
    dm = dell.get("DellMemory")
    if not isinstance(dm, dict):
        return
    mfg = dm.get("ManufactureDate")
    if isinstance(mfg, str):
        parsed = parse_dell_oem_manufacture_date(mfg)
        if parsed is not None:
            wk, yr, iso_date = parsed
            rp["ManufactureWeek"] = wk
            rp["ManufactureYear"] = yr
            rp["ManufactureDate"] = iso_date


def _dell_memory_has_inline_manufacture_date(data: Dict[str, Any]) -> bool:
    oem = data.get("Oem")
    if not isinstance(oem, dict):
        return False
    dell = oem.get("Dell")
    if not isinstance(dell, dict):
        return False
    dm = dell.get("DellMemory")
    if not isinstance(dm, dict):
        return False
    mfg = dm.get("ManufactureDate")
    return isinstance(mfg, str) and bool(mfg.strip())


def _dell_assembly_member_id_from_memory(data: Dict[str, Any]) -> Optional[str]:
    """Map a Memory resource to chassis ``Assembly`` member id (e.g. ``DIMM.Socket.A1``)."""
    mid = data.get("Id")
    if isinstance(mid, str) and mid.startswith("DIMM.Socket."):
        return mid
    name = data.get("Name")
    if isinstance(name, str):
        m = re.match(r"^DIMM\s+([AB])(\d+)$", name.strip(), re.I)
        if m:
            return f"DIMM.Socket.{m.group(1).upper()}{m.group(2)}"
    if isinstance(mid, str) and "DIMMSLOT" in mid.upper():
        m = re.search(r"DIMMSLOT([AB])(\d+)", mid, re.I)
        if m:
            return f"DIMM.Socket.{m.group(1).upper()}{m.group(2)}"
    return None


def _dell_memory_assembly_redfish_path(data: Dict[str, Any]) -> Optional[str]:
    """Redfish path for the DIMM's Assembly document, or ``None``."""
    asm = data.get("Assembly")
    if isinstance(asm, dict):
        ref = asm.get("@odata.id")
        if isinstance(ref, str) and ref.strip():
            path = assembly_odata_path(ref)
            if "/Memory/" in path and path.endswith("/Assembly"):
                return path
            if path.endswith("/Assembly") and "/Chassis/" in path:
                member = _dell_assembly_member_id_from_memory(data)
                if member:
                    return f"{path}/{member}"
    links = data.get("Links")
    if isinstance(links, dict):
        chassis = links.get("Chassis")
        if isinstance(chassis, dict):
            cref = chassis.get("@odata.id")
            if isinstance(cref, str) and cref.strip():
                member = _dell_assembly_member_id_from_memory(data)
                if member:
                    base = assembly_odata_path(cref)
                    return f"{base}/Assembly/{member}"
    return None


def _production_date_from_memory_assembly_payload(
    data: Dict[str, Any],
) -> Optional[str]:
    pd = data.get("ProductionDate")
    if isinstance(pd, str) and pd.strip():
        return pd.strip()
    return production_date_from_assembly_payload(data)


def _part_number_from_memory_assembly_payload(data: Dict[str, Any]) -> Optional[str]:
    """Read ``PartNumber`` from a single ``AssemblyData`` block or the first ``Assemblies[]`` entry."""
    pn = data.get("PartNumber")
    if isinstance(pn, str) and pn.strip():
        return pn.strip()
    assemblies = data.get("Assemblies") or []
    if isinstance(assemblies, list):
        for block in assemblies:
            if isinstance(block, dict):
                pn = block.get("PartNumber")
                if isinstance(pn, str) and pn.strip():
                    return pn.strip()
    return None


def prefetch_dell_memory_assembly_manufacture(ctx: NormalizationContext) -> None:
    """Prefetch DIMM ``Assembly`` (``ProductionDate`` + ``PartNumber``) into ``ctx.prefetched``.

    Always fetched when Dell and an ``Assembly`` link resolves, even when
    ``ManufactureDate`` is already inline (e.g. R740/R7525 ``DellMemory``), because
    the FRU ``PartNumber`` is only available from ``Assembly`` — never inline.
    """
    path = _dell_memory_assembly_redfish_path(ctx.data)
    if not path:
        return
    try:
        payload = redfish_get_json(ctx.client, path)
    except Exception:  # noqa: BLE001
        return
    if not isinstance(payload, dict):
        return
    result: Dict[str, Any] = {}
    if not _dell_memory_has_inline_manufacture_date(ctx.data):
        pd = _production_date_from_memory_assembly_payload(payload)
        if pd is not None:
            parsed = parse_dell_assembly_production_date(pd)
            if parsed is not None:
                wk, yr, iso_date = parsed
                result["ManufactureWeek"] = wk
                result["ManufactureYear"] = yr
                result["ManufactureDate"] = iso_date
    fru_part_number = _part_number_from_memory_assembly_payload(payload)
    if fru_part_number:
        result["FruPartNumber"] = fru_part_number
    block = payload
    if isinstance(payload.get("Assemblies"), list):
        member = _dell_assembly_member_id_from_memory(ctx.data)
        if member:
            picked = select_assembly_block(payload, member)
            if isinstance(picked, dict):
                block = picked
    for key, val in redpool_fields_from_assembly_block(block).items():
        if key not in result or not result.get(key):
            result[key] = val
    if not result:
        return
    if ctx.prefetched is None:
        ctx.prefetched = {}
    ctx.prefetched[_DELL_MEMORY_ASSEMBLY_MFG] = result


def apply_prefetched_dell_memory_assembly_manufacture(
    rp: Dict[str, Any], ctx: NormalizationContext
) -> None:
    """Copy prefetched Assembly manufacture/FRU fields into ``rp`` when not already set."""
    mfg = (ctx.prefetched or {}).get(_DELL_MEMORY_ASSEMBLY_MFG)
    if not isinstance(mfg, dict):
        return
    if not rp.get("ManufactureDate"):
        for key in ("ManufactureWeek", "ManufactureYear", "ManufactureDate"):
            if key in mfg and (key not in rp or rp.get(key) in (None, "")):
                rp[key] = mfg[key]
    fru_part_number = mfg.get("FruPartNumber")
    if fru_part_number and not rp.get("FruPartNumber"):
        rp["FruPartNumber"] = fru_part_number


_MemoryLocationQuad = Tuple[int, int, int, int]

_R630: Dict[str, _MemoryLocationQuad] = {
    "DIMM A1": (0, 0, 0, 0),
    "DIMM A5": (0, 0, 0, 1),
    "DIMM A9": (0, 0, 0, 2),
    "DIMM A2": (0, 0, 1, 0),
    "DIMM A6": (0, 0, 1, 1),
    "DIMM A10": (0, 0, 1, 2),
    "DIMM A3": (0, 1, 2, 0),
    "DIMM A7": (0, 1, 2, 1),
    "DIMM A11": (0, 1, 2, 2),
    "DIMM A4": (0, 1, 3, 0),
    "DIMM A8": (0, 1, 3, 1),
    "DIMM A12": (0, 1, 3, 2),
    "DIMM B1": (1, 0, 0, 0),
    "DIMM B5": (1, 0, 0, 1),
    "DIMM B9": (1, 0, 0, 2),
    "DIMM B2": (1, 0, 1, 0),
    "DIMM B6": (1, 0, 1, 1),
    "DIMM B10": (1, 0, 1, 2),
    "DIMM B3": (1, 1, 2, 0),
    "DIMM B7": (1, 1, 2, 1),
    "DIMM B11": (1, 1, 2, 2),
    "DIMM B4": (1, 1, 3, 0),
    "DIMM B8": (1, 1, 3, 1),
    "DIMM B12": (1, 1, 3, 2),
}

# Channels 0-5 are socket-scoped (Dell Tech Guide); MC0 owns 0-2, MC1 owns 3-5.
_R740: Dict[str, _MemoryLocationQuad] = {
    "DIMM A1": (0, 0, 0, 0),
    "DIMM A7": (0, 0, 0, 1),
    "DIMM A2": (0, 0, 1, 0),
    "DIMM A8": (0, 0, 1, 1),
    "DIMM A3": (0, 0, 2, 0),
    "DIMM A9": (0, 0, 2, 1),
    "DIMM A4": (0, 1, 3, 0),
    "DIMM A10": (0, 1, 3, 1),
    "DIMM A5": (0, 1, 4, 0),
    "DIMM A11": (0, 1, 4, 1),
    "DIMM A6": (0, 1, 5, 0),
    "DIMM A12": (0, 1, 5, 1),
    "DIMM B1": (1, 0, 0, 0),
    "DIMM B7": (1, 0, 0, 1),
    "DIMM B2": (1, 0, 1, 0),
    "DIMM B8": (1, 0, 1, 1),
    "DIMM B3": (1, 0, 2, 0),
    "DIMM B9": (1, 0, 2, 1),
    "DIMM B4": (1, 1, 3, 0),
    "DIMM B10": (1, 1, 3, 1),
    "DIMM B5": (1, 1, 4, 0),
    "DIMM B11": (1, 1, 4, 1),
    "DIMM B6": (1, 1, 5, 0),
    "DIMM B12": (1, 1, 5, 1),
}

_R7525: Dict[str, _MemoryLocationQuad] = {
    "DIMM A6": (0, 0, 0, 0),
    "DIMM A12": (0, 0, 0, 1),
    "DIMM A5": (0, 0, 1, 0),
    "DIMM A11": (0, 0, 1, 1),
    "DIMM A2": (0, 1, 2, 0),
    "DIMM A10": (0, 1, 2, 1),
    "DIMM A1": (0, 1, 3, 0),
    "DIMM A9": (0, 1, 3, 1),
    "DIMM A8": (0, 2, 4, 0),
    "DIMM A16": (0, 2, 4, 1),
    "DIMM A7": (0, 2, 5, 0),
    "DIMM A15": (0, 2, 5, 1),
    "DIMM A4": (0, 3, 6, 0),
    "DIMM A14": (0, 3, 6, 1),
    "DIMM A3": (0, 3, 7, 0),
    "DIMM A13": (0, 3, 7, 1),
    "DIMM B6": (1, 0, 0, 0),
    "DIMM B12": (1, 0, 0, 1),
    "DIMM B5": (1, 0, 1, 0),
    "DIMM B11": (1, 0, 1, 1),
    "DIMM B2": (1, 1, 2, 0),
    "DIMM B10": (1, 1, 2, 1),
    "DIMM B1": (1, 1, 3, 0),
    "DIMM B9": (1, 1, 3, 1),
    "DIMM B8": (1, 2, 4, 0),
    "DIMM B16": (1, 2, 4, 1),
    "DIMM B7": (1, 2, 5, 0),
    "DIMM B15": (1, 2, 5, 1),
    "DIMM B4": (1, 3, 6, 0),
    "DIMM B14": (1, 3, 6, 1),
    "DIMM B3": (1, 3, 7, 0),
    "DIMM B13": (1, 3, 7, 1),
}

# 12 channels, 1 DPC (Dell R7625 ISM). Channels are socket-scoped; MC = channel // 2.
_R7625: Dict[str, _MemoryLocationQuad] = {
    "DIMM A1": (0, 0, 0, 0),
    "DIMM A5": (0, 0, 1, 0),
    "DIMM A3": (0, 1, 2, 0),
    "DIMM A9": (0, 1, 3, 0),
    "DIMM A7": (0, 2, 4, 0),
    "DIMM A11": (0, 2, 5, 0),
    "DIMM A2": (0, 3, 6, 0),
    "DIMM A6": (0, 3, 7, 0),
    "DIMM A4": (0, 4, 8, 0),
    "DIMM A10": (0, 4, 9, 0),
    "DIMM A8": (0, 5, 10, 0),
    "DIMM A12": (0, 5, 11, 0),
    "DIMM B1": (1, 0, 0, 0),
    "DIMM B5": (1, 0, 1, 0),
    "DIMM B3": (1, 1, 2, 0),
    "DIMM B9": (1, 1, 3, 0),
    "DIMM B7": (1, 2, 4, 0),
    "DIMM B11": (1, 2, 5, 0),
    "DIMM B2": (1, 3, 6, 0),
    "DIMM B6": (1, 3, 7, 0),
    "DIMM B4": (1, 4, 8, 0),
    "DIMM B10": (1, 4, 9, 0),
    "DIMM B8": (1, 5, 10, 0),
    "DIMM B12": (1, 5, 11, 0),
}

_R760: Dict[str, _MemoryLocationQuad] = {
    "DIMM A1": (0, 0, 0, 0),
    "DIMM A9": (0, 0, 0, 1),
    "DIMM A7": (0, 0, 1, 0),
    "DIMM A15": (0, 0, 1, 1),
    "DIMM A3": (0, 1, 2, 0),
    "DIMM A11": (0, 1, 2, 1),
    "DIMM A5": (0, 1, 3, 0),
    "DIMM A13": (0, 1, 3, 1),
    "DIMM A4": (0, 2, 4, 0),
    "DIMM A12": (0, 2, 4, 1),
    "DIMM A6": (0, 2, 5, 0),
    "DIMM A14": (0, 2, 5, 1),
    "DIMM A2": (0, 3, 6, 0),
    "DIMM A10": (0, 3, 6, 1),
    "DIMM A8": (0, 3, 7, 0),
    "DIMM A16": (0, 3, 7, 1),
    "DIMM B1": (1, 0, 0, 0),
    "DIMM B9": (1, 0, 0, 1),
    "DIMM B7": (1, 0, 1, 0),
    "DIMM B15": (1, 0, 1, 1),
    "DIMM B3": (1, 1, 2, 0),
    "DIMM B11": (1, 1, 2, 1),
    "DIMM B5": (1, 1, 3, 0),
    "DIMM B13": (1, 1, 3, 1),
    "DIMM B4": (1, 2, 4, 0),
    "DIMM B12": (1, 2, 4, 1),
    "DIMM B6": (1, 2, 5, 0),
    "DIMM B14": (1, 2, 5, 1),
    "DIMM B2": (1, 3, 6, 0),
    "DIMM B10": (1, 3, 6, 1),
    "DIMM B8": (1, 3, 7, 0),
    "DIMM B16": (1, 3, 7, 1),
}

_LOCATOR_MAP: Dict[tuple[str, str], Dict[str, _MemoryLocationQuad]] = {
    ("dell", "poweredger630"): _R630,
    ("dell", "poweredger740"): _R740,
    # R6525 ISM uses the same 8-channel 2-DPC silk as R7525.
    ("dell", "poweredger6525"): _R7525,
    ("dell", "poweredger7525"): _R7525,
    ("dell", "poweredger760"): _R760,
    ("dell", "poweredger7625"): _R7625,
}


def _model_fold(model: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (model or "").lower())


def _dell_memory_locator_lookup_strings(ctx: NormalizationContext) -> list[str]:
    """Strings for map lookup: iDRAC ``Memory.Name`` only."""
    name = ctx.data.get("Name")
    if isinstance(name, str) and name.strip():
        return [name.strip()]
    return []


def dell_locator_strings_to_canonical_memory_location(
    vendor_fold: str,
    model_fold: str,
    strings: Sequence[str],
) -> Optional[_MemoryLocationQuad]:
    """Return canonical ``(Socket, MemoryController, Channel, Slot)``, or ``None``.

    Dell mapping is keyed by iDRAC ``Memory.Name``-style strings (e.g. ``DIMM A1``). The
    first ``strings`` entry that matches a row for ``(vendor_fold, model_fold)`` wins.
    Non-Dell ``vendor_fold`` always returns ``None``.
    """
    tab = _LOCATOR_MAP.get((vendor_fold, model_fold))
    if not tab:
        return None
    for s in strings:
        if s in tab:
            return tab[s]
    return None


def locator_to_location(ctx: NormalizationContext) -> Optional[_MemoryLocationQuad]:
    """Read canonical coordinates from the silk map when ``MemoryLocation`` is absent."""
    strings = _dell_memory_locator_lookup_strings(ctx)
    if not strings:
        return None
    return dell_locator_strings_to_canonical_memory_location(
        "dell", _model_fold(ctx.model), strings
    )


__all__ = [
    "apply_prefetched_dell_memory_assembly_manufacture",
    "dell_locator_strings_to_canonical_memory_location",
    "extend_redpool_from_dell_oem",
    "locator_to_location",
    "parse_dell_oem_manufacture_date",
    "prefetch_dell_memory_assembly_manufacture",
]
