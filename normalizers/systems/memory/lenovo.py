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


# SR650 V2 reports the controller and socket-wide channel directly. The table
# gives the within-channel slot for board DIMMs 1–16 (17–32 on socket 2).
# https://pubs.lenovo.com/sr650-v2/dimm_installation_rules_2
_SR650_V2_SLOTS = (0, 1, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 0)

# Board DIMM number -> (socket, memory controller, socket-wide channel, slot).
# https://pubs.lenovo.com/sr680a-v3/memory_module_installation_order
# https://pubs.lenovo.com/sr780a-v3/memory_module_installation_order
_SR680A_LOCATIONS: Dict[int, _MemoryLocationQuad] = {
    1: (0, 3, 7, 0),
    2: (0, 3, 7, 1),
    3: (0, 3, 6, 0),
    4: (0, 3, 6, 1),
    5: (0, 2, 5, 0),
    6: (0, 2, 5, 1),
    7: (0, 2, 4, 0),
    8: (0, 2, 4, 1),
    9: (0, 0, 0, 1),
    10: (0, 0, 0, 0),
    11: (0, 0, 1, 1),
    12: (0, 0, 1, 0),
    13: (0, 1, 2, 1),
    14: (0, 1, 2, 0),
    15: (0, 1, 3, 1),
    16: (0, 1, 3, 0),
    17: (1, 3, 7, 0),
    18: (1, 3, 7, 1),
    19: (1, 3, 6, 0),
    20: (1, 3, 6, 1),
    21: (1, 2, 5, 0),
    22: (1, 2, 5, 1),
    23: (1, 2, 4, 0),
    24: (1, 2, 4, 1),
    25: (1, 0, 0, 1),
    26: (1, 0, 0, 0),
    27: (1, 0, 1, 1),
    28: (1, 0, 1, 0),
    29: (1, 1, 2, 1),
    30: (1, 1, 2, 0),
    31: (1, 1, 3, 1),
    32: (1, 1, 3, 0),
}
# The combined system model string appears in the ThinkSystem_SR680a_V3_910 capture
# under fixtures/Lenovo/. Both model manuals above specify the same DIMM layout.
_SR680A_MODELS = {
    "thinksystemsr680av3",
    "thinksystemsr680asr780av3",
    "thinksystemsr780av3",
}


def lenovo_bmc_to_canonical_memory_location(
    model_fold: str,
    socket: int,
    memory_controller: int,
    channel: int,
    slot: int,
) -> Optional[_MemoryLocationQuad]:
    """Return canonical ``(Socket, MemoryController, Channel, Slot)``, or ``None`` if unmapped."""
    # SR675 V3 installation guide, Table 1: one DIMM socket per channel.
    # https://pubs.lenovo.com/sr675-v3/memory_module_installation_order
    if model_fold == "thinksystemsr675v3":
        return _dec1_bmc_socket(socket), memory_controller, channel, 0

    if model_fold in _SR680A_MODELS:
        location = _SR680A_LOCATIONS.get(slot)
        if location is not None and socket == location[0] + 1:
            return location
        return None

    if model_fold != "thinksystemsr650v2" or not 1 <= slot <= 32:
        return None

    board_socket, position = divmod(slot - 1, 16)
    if socket != board_socket + 1:
        return None
    return board_socket, memory_controller, channel, _SR650_V2_SLOTS[position]


__all__ = [
    "extend_redpool_from_lenovo_oem",
    "iso_date_from_iso_week",
    "lenovo_bmc_to_canonical_memory_location",
    "parse_lenovo_oem_manufacture_week_year",
]
