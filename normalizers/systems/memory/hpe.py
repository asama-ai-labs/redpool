# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE memory: ``DIMMManufacturingDate`` (``YYWW``), ``Oem.Redpool`` merge, and BMC ``MemoryLocation`` maps."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional, Tuple

_ModelFold = str
_MemoryLocationQuad = Tuple[int, int, int, int]


def _coerce_dimmm_manufacturing_date(raw: Any) -> Optional[str]:
    if isinstance(raw, str):
        s = raw.strip()
        return s if s else None
    if isinstance(raw, int) and 0 <= raw <= 9999:
        return f"{raw:04d}"
    return None


def parse_hpe_dimmm_manufacturing_date(raw: Any) -> Optional[Tuple[int, int, str]]:
    """Parse ``DIMMManufacturingDate`` ``YYWW`` → ``(week, full_year, ManufactureDate)``.

    ``YY`` is expanded as ``2000 + YY``. ``week`` is the WW field (1–53). ``ManufactureDate``
    is the Monday of that ISO week in ``full_year`` (``YYYY-MM-DD``).
    """
    s = _coerce_dimmm_manufacturing_date(raw)
    if s is None or len(s) != 4 or not s.isdigit():
        return None
    yy = int(s[:2])
    ww = int(s[2:])
    if not (1 <= ww <= 53):
        return None
    full_year = 2000 + yy
    try:
        monday = date.fromisocalendar(full_year, ww, 1)
    except ValueError:
        return None
    return (ww, full_year, monday.isoformat())


def extend_redpool_from_hpe_oem(rp: Dict[str, Any], hpe: Dict[str, Any]) -> None:
    """Merge HPE OEM fields into ``Oem.Redpool`` (mutates ``rp``)."""
    mfg = hpe.get("DIMMManufacturingDate")
    parsed = parse_hpe_dimmm_manufacturing_date(mfg)
    if parsed is not None:
        wk, yr, iso_date = parsed
        rp["ManufactureWeek"] = wk
        rp["ManufactureYear"] = yr
        rp["ManufactureDate"] = iso_date
    # HPE Smart Memory FRU string (e.g. Gen11 ``P43333-0A1``); distinct from top-level DIMM ``PartNumber``.
    fru = hpe.get("PartNumber")
    if isinstance(fru, str):
        s = fru.strip()
        if s and s.lower() != "unknown":
            rp["FruPartNumber"] = s


# HPE Oem.Hpe.DIMMStatus → (Health, State, HealthRollup). Unknown statuses leave Status unchanged.
_HPE_DIMM_STATUS_MAP: Dict[str, tuple[str, str, str]] = {
    "GoodInUse": ("OK", "Enabled", "OK"),
    "GoodPartiallyInUse": ("OK", "Enabled", "OK"),
    "NotPresent": ("OK", "Absent", "OK"),
    "Present": ("OK", "Enabled", "OK"),
    "Degraded": ("Warning", "Enabled", "Warning"),
    "DegradedInUse": ("Warning", "Enabled", "Warning"),
    "Failed": ("Critical", "Enabled", "Critical"),
    "FailedInUse": ("Critical", "Enabled", "Critical"),
    "Spare": ("OK", "StandbySpare", "OK"),
    "SpareInUse": ("OK", "Enabled", "OK"),
}


def map_hpe_dimm_status(dimm_status: Any) -> Optional[Dict[str, str]]:
    """Map Oem.Hpe.DIMMStatus string to a Status dict, or None if unmapped."""
    if not isinstance(dimm_status, str):
        return None
    key = dimm_status.strip()
    mapped = _HPE_DIMM_STATUS_MAP.get(key)
    if mapped is None:
        return None
    health, state, rollup = mapped
    return {"Health": health, "State": state, "HealthRollup": rollup}


def effective_hpe_memory_manufacturer(manufacturer: Any, hpe: Dict[str, Any]) -> Any:
    """Prefer Oem.Hpe.VendorName when Manufacturer is empty or the brand (HPE/Hewlett Packard)."""
    vendor = hpe.get("VendorName")
    if not isinstance(vendor, str) or not vendor.strip():
        return manufacturer
    vendor_s = vendor.strip()
    mfr = manufacturer.strip() if isinstance(manufacturer, str) else ""
    if not mfr:
        return vendor_s
    mfr_l = mfr.lower()
    if mfr_l in (
        "hpe",
        "hp",
        "hewlett packard enterprise",
        "hewlett-packard",
        "hewlett packard",
    ):
        return vendor_s
    return manufacturer


# HPE QuickSpecs, Memory Population guidelines: slot 0 is the first socket to
# populate in a channel (white connector). DL360 and DL380 Gen10 share a layout.
# https://www.hpe.com/psnow/doc/a00008159enw (DL360 Gen10)
# https://www.hpe.com/psnow/doc/a00008180enw (DL380 Gen10)
_HPE_GEN10_INTEL_2S_2DPC_BMC_TO_CANONICAL: Dict[
    _MemoryLocationQuad, _MemoryLocationQuad
] = {
    (1, 1, 1, 7): (0, 0, 0, 1),
    (1, 1, 1, 8): (0, 0, 0, 0),
    (1, 1, 2, 9): (0, 0, 1, 1),
    (1, 1, 2, 10): (0, 0, 1, 0),
    (1, 1, 3, 11): (0, 0, 2, 1),
    (1, 1, 3, 12): (0, 0, 2, 0),
    (1, 2, 4, 5): (0, 1, 3, 0),
    (1, 2, 4, 6): (0, 1, 3, 1),
    (1, 2, 5, 3): (0, 1, 4, 0),
    (1, 2, 5, 4): (0, 1, 4, 1),
    (1, 2, 6, 1): (0, 1, 5, 0),
    (1, 2, 6, 2): (0, 1, 5, 1),
    (2, 3, 1, 7): (1, 0, 0, 1),
    (2, 3, 1, 8): (1, 0, 0, 0),
    (2, 3, 2, 9): (1, 0, 1, 1),
    (2, 3, 2, 10): (1, 0, 1, 0),
    (2, 3, 3, 11): (1, 0, 2, 1),
    (2, 3, 3, 12): (1, 0, 2, 0),
    (2, 4, 4, 5): (1, 1, 3, 0),
    (2, 4, 4, 6): (1, 1, 3, 1),
    (2, 4, 5, 3): (1, 1, 4, 0),
    (2, 4, 5, 4): (1, 1, 4, 1),
    (2, 4, 6, 1): (1, 1, 5, 0),
    (2, 4, 6, 2): (1, 1, 5, 1),
}

# Input tuples come from iLO MemoryLocation fields in the matching captures under
# fixtures/HPE/<model>/original/redfish/v1/Systems/1/Memory/.
# model_fold → BMC quadruple → canonical ``(Socket, MemoryController, Channel, Slot)``
_HPE_BMC_TO_CANONICAL_MEMORY_LOCATION: Dict[
    _ModelFold, Dict[_MemoryLocationQuad, _MemoryLocationQuad]
] = {
    "proliantdl360gen10": _HPE_GEN10_INTEL_2S_2DPC_BMC_TO_CANONICAL,
    "proliantdl380gen10": _HPE_GEN10_INTEL_2S_2DPC_BMC_TO_CANONICAL,
    # DL385 Gen10 Plus QuickSpecs, Memory diagram. Channel follows the board
    # lettering (A=0), independently of the iLO memory controller index.
    # https://www.hpe.com/psnow/doc/a00073549enw (v23, p. 48, Memory)
    "proliantdl385gen10plus": {
        (1, 1, 1, 9): (0, 0, 0, 1),
        (1, 1, 1, 10): (0, 0, 0, 0),
        (1, 2, 2, 11): (0, 1, 1, 1),
        (1, 2, 2, 12): (0, 1, 1, 0),
        (1, 3, 3, 15): (0, 2, 3, 1),
        (1, 3, 3, 16): (0, 2, 3, 0),
        (1, 4, 4, 13): (0, 3, 2, 1),
        (1, 4, 4, 14): (0, 3, 2, 0),
        (1, 5, 5, 1): (0, 4, 7, 0),
        (1, 5, 5, 2): (0, 4, 7, 1),
        (1, 6, 6, 3): (0, 5, 6, 0),
        (1, 6, 6, 4): (0, 5, 6, 1),
        (1, 7, 7, 7): (0, 6, 4, 0),
        (1, 7, 7, 8): (0, 6, 4, 1),
        (1, 8, 8, 5): (0, 7, 5, 0),
        (1, 8, 8, 6): (0, 7, 5, 1),
        (2, 9, 1, 9): (1, 0, 0, 1),
        (2, 9, 1, 10): (1, 0, 0, 0),
        (2, 10, 2, 11): (1, 1, 1, 1),
        (2, 10, 2, 12): (1, 1, 1, 0),
        (2, 11, 3, 15): (1, 2, 3, 1),
        (2, 11, 3, 16): (1, 2, 3, 0),
        (2, 12, 4, 13): (1, 3, 2, 1),
        (2, 12, 4, 14): (1, 3, 2, 0),
        (2, 13, 5, 1): (1, 4, 7, 0),
        (2, 13, 5, 2): (1, 4, 7, 1),
        (2, 14, 6, 3): (1, 5, 6, 0),
        (2, 14, 6, 4): (1, 5, 6, 1),
        (2, 15, 7, 7): (1, 6, 4, 0),
        (2, 15, 7, 8): (1, 6, 4, 1),
        (2, 16, 8, 5): (1, 7, 5, 0),
        (2, 16, 8, 6): (1, 7, 5, 1),
    },
    # DL380a Gen11 QuickSpecs, “Memory Population guidelines”: slot layout and first-populated slots.
    # https://support.hpe.com/hpesc/public/api/document/a50004309enw
    "proliantdl380agen11": {
        (1, 1, 1, 7): (0, 0, 0, 1),
        (1, 1, 1, 8): (0, 0, 0, 0),
        (1, 1, 2, 9): (0, 0, 1, 0),
        (1, 2, 3, 10): (0, 1, 2, 1),
        (1, 2, 3, 11): (0, 1, 2, 0),
        (1, 2, 4, 12): (0, 1, 3, 0),
        (1, 3, 5, 5): (0, 2, 4, 0),
        (1, 3, 5, 6): (0, 2, 4, 1),
        (1, 3, 6, 4): (0, 2, 5, 0),
        (1, 4, 7, 2): (0, 3, 6, 0),
        (1, 4, 7, 3): (0, 3, 6, 1),
        (1, 4, 8, 1): (0, 3, 7, 0),
        (2, 5, 1, 7): (1, 0, 0, 1),
        (2, 5, 1, 8): (1, 0, 0, 0),
        (2, 5, 2, 9): (1, 0, 1, 0),
        (2, 6, 3, 10): (1, 1, 2, 1),
        (2, 6, 3, 11): (1, 1, 2, 0),
        (2, 6, 4, 12): (1, 1, 3, 0),
        (2, 7, 5, 5): (1, 2, 4, 0),
        (2, 7, 5, 6): (1, 2, 4, 1),
        (2, 7, 6, 4): (1, 2, 5, 0),
        (2, 8, 7, 2): (1, 3, 6, 0),
        (2, 8, 7, 3): (1, 3, 6, 1),
        (2, 8, 8, 1): (1, 3, 7, 0),
    },
}


def hpe_bmc_to_canonical_memory_location(
    model_fold: str, socket: int, memory_controller: int, channel: int, slot: int
) -> Optional[_MemoryLocationQuad]:
    """Return canonical ``(Socket, MemoryController, Channel, Slot)``, or ``None``."""
    tab = _HPE_BMC_TO_CANONICAL_MEMORY_LOCATION.get(model_fold)
    if not tab:
        return None
    return tab.get((socket, memory_controller, channel, slot))


__all__ = [
    "effective_hpe_memory_manufacturer",
    "extend_redpool_from_hpe_oem",
    "hpe_bmc_to_canonical_memory_location",
    "map_hpe_dimm_status",
    "parse_hpe_dimmm_manufacturing_date",
]
