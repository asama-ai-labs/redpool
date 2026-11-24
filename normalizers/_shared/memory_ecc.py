# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Shared helpers for Redfish ``Memory.ErrorCorrection`` (memory + processor normalizers)."""

from __future__ import annotations

from typing import Iterable, Optional

# Redfish values that indicate ECC-capable DRAM (vs AddressParity-only, NoECC, etc.).
_RAM_ECC_SCHEMES = frozenset({"SingleBitECC", "MultiBitECC", "ChipKill"})


def memory_error_correction_indicates_ram_ecc(value: object) -> bool:
    """Return True when *value* is a standard ECC DRAM correction scheme."""
    return isinstance(value, str) and value.strip() in _RAM_ECC_SCHEMES


def memory_ecc_mode_enabled(error_corrections: Iterable[object]) -> Optional[bool]:
    """``MemorySummary.ECCModeEnabled`` from each DIMM's own ``ErrorCorrection``.

    ``False`` when any DIMM reports a scheme that is not ECC, ``None`` when no DIMM does
    but at least one reports nothing (the BMC did not say, so ECC mode is unknown),
    ``True`` when every DIMM reports an ECC scheme.
    """
    unknown = False
    for value in error_corrections:
        if isinstance(value, str) and value.strip():
            if not memory_error_correction_indicates_ram_ecc(value):
                return False
        else:
            unknown = True
    return None if unknown else True
