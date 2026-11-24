# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo memory: OEM ``ManufactureDate`` text, and ``MemoryLocation`` DPC / slot mapping.

**Memory location** — BMC ``Socket`` is 1-based; ``MemoryController`` and ``Channel`` are
0-based on the wire. ``Slot`` is 1-based and **global** (not per channel). Use
``lenovo_bmc_to_canonical_memory_location`` for the canonical quadruple. Unlisted models
return ``None`` and ``generate_memory_location`` passes BMC values through unchanged.

**Manufacture / FRU / ECC** — :func:`extend_redpool_from_lenovo_oem` fills ``Oem.Redpool`` from
``Oem.Lenovo`` (uses :func:`parse_lenovo_oem_manufacture_week_year` for ``ManufactureDate`` text).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Optional, Tuple

_MemoryLocationQuad = Tuple[int, int, int, int]


def parse_lenovo_oem_manufacture_week_year(text: str) -> Optional[Tuple[int, int]]:
    """Parse Lenovo ``ManufactureDate`` like ``year 2024 week 17`` → ``(week, calendar_year)``."""
    if not isinstance(text, str):
        return None
    m = re.search(r"year\s+(\d{4})\s+week\s+(\d{1,2})", text, re.I)
    if not m:
        return None
    year_full = int(m.group(1))
    week = int(m.group(2))
    if not (1 <= week <= 53):
        return None
    return (week, year_full)


def iso_date_from_iso_week(year: int, week: int) -> Optional[str]:
    """Monday of ISO week ``(year, week)`` as ``YYYY-MM-DD`` (same rule as HPE ``DIMMManufacturingDate``)."""
    if not (1 <= week <= 53):
        return None
    try:
        return date.fromisocalendar(year, week, 1).isoformat()
    except ValueError:
        return None


def extend_redpool_from_lenovo_oem(rp: Dict[str, Any], lenovo: Dict[str, Any]) -> None:
    """Merge Lenovo OEM fields into ``Oem.Redpool`` (mutates ``rp``)."""
    md = lenovo.get("ManufactureDate")
    if isinstance(md, str):
        wy = parse_lenovo_oem_manufacture_week_year(md)
        if wy is not None:
            wk, yr = wy
            rp["ManufactureWeek"] = wk
            rp["ManufactureYear"] = yr
            iso = iso_date_from_iso_week(yr, wk)
            if iso is not None:
                rp["ManufactureDate"] = iso
    fru = lenovo.get("FruPartNumber")
    if isinstance(fru, str) and fru.strip():
        rp["FruPartNumber"] = fru.strip()
    ecc = lenovo.get("EccBits")
    if isinstance(ecc, int):
        rp["EccBits"] = ecc


def _dec1_bmc_socket(v: int) -> int:
    """Map 1-based BMC ``Socket`` to 0-based; leave ``0`` unchanged."""
    return v - 1 if v >= 1 else v


# ``model_fold`` → max DIMM slots per memory channel (1 / 2 / 3).
_MODEL_MEMORY_SLOTS_PER_CHANNEL: Dict[str, int] = {
    "thinksystemsr650v2": 2,
    "thinksystemsr675v3": 1,
    "thinksystemsr680av3": 2,
}


def _memory_slots_per_channel(model_fold: str) -> Optional[int]:
    """Return 1–3 for known models, else ``None`` (caller should passthrough)."""
    dpc = _MODEL_MEMORY_SLOTS_PER_CHANNEL.get(model_fold)
    if dpc is None:
        return None
    return max(1, min(3, int(dpc)))


def _bmc_slot_to_channel_index(model_fold: str, slot: int) -> Optional[int]:
    """Map 1-based BMC *global* ``slot`` to 0-based index within the channel.

    Uses ``_memory_slots_per_channel(model_fold)``. Returns ``None`` if the model has no
    DPC entry (caller should not transform ``Slot``).

    * DPC ``1`` (1DPC): always ``0``.
    * ``2`` (2DPC): ``(slot - 1) % 2``.
    * ``3`` (3DPC): ``(slot - 1) % 3``.
    """
    spc = _memory_slots_per_channel(model_fold)
    if spc is None:
        return None
    spc = max(1, min(3, spc))
    if spc == 1:
        return 0
    return (slot - 1) % spc


def lenovo_bmc_to_canonical_memory_location(
    model_fold: str,
    socket: int,
    memory_controller: int,
    channel: int,
    slot: int,
) -> Optional[_MemoryLocationQuad]:
    """Return canonical ``(Socket, MemoryController, Channel, Slot)``, or ``None`` if unmapped."""
    slot_idx = _bmc_slot_to_channel_index(model_fold, slot)
    if slot_idx is None:
        return None
    return (
        _dec1_bmc_socket(socket),
        memory_controller,
        channel,
        slot_idx,
    )


__all__ = [
    "extend_redpool_from_lenovo_oem",
    "iso_date_from_iso_week",
    "lenovo_bmc_to_canonical_memory_location",
    "parse_lenovo_oem_manufacture_week_year",
]
