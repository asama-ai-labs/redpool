# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""PCI class code normalization utilities.

Some vendors appear to serialize the 24-bit PCI class code in reversed byte order
(e.g. 0x000006 instead of 0x060000 for a Bridge). Normalize to big-endian 0xRRGGPP
as lowercase ``0x`` + 6 hex digits (e.g. ``0x060000``, ``0x010000``).
"""

from __future__ import annotations

import re
from typing import Any

# PCIeFunction VendorId/DeviceId/Subsystem* are two bytes; RevisionId is one byte.
_PCI_ID_PATTERN = {
    1: re.compile(r"^0[xX]([0-9A-Fa-f]{2}){1}$"),
    2: re.compile(r"^0[xX]([0-9A-Fa-f]{2}){2}$"),
}


def _canonical_pci_class_24(v: int) -> str:
    """Map 24-bit class code to canonical big-endian hex string."""
    v &= 0xFFFFFF
    b0 = (v >> 0) & 0xFF
    b1 = (v >> 8) & 0xFF
    b2 = (v >> 16) & 0xFF
    rev = (b0 << 16) | (b1 << 8) | (b2 << 0)

    # If it looks like little-endian (high byte zero but low byte non-zero), reverse.
    if (v & 0xFF0000) == 0 and (v & 0x0000FF) != 0:
        v = rev

    return f"0x{v:06x}"


def normalize_pci_class_code(value: object) -> object:
    """Normalize a PCI class code to canonical ``0x`` + 6 lowercase hex digits.

    - Accepts ``int`` (24-bit value, any byte order vendor quirk handled like strings).
    - Accepts strings like ``0x000006``, ``0X000001``, ``000006``, or ``1``.
    - Returns the original value for unsupported types or unparsable strings.
    """

    if isinstance(value, int):
        return _canonical_pci_class_24(value)
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    if s.startswith(("0x", "0X")):
        s_hex = s[2:]
    else:
        s_hex = s
    try:
        v = int(s_hex, 16) & 0xFFFFFF
    except ValueError:
        return value

    return _canonical_pci_class_24(v)


def normalize_pcie_function_class_code_inplace(
    body: Any, *, enabled: bool = True
) -> None:
    """Canonicalize ClassCode and PCI ids on a PCIeFunction body.

    Some vendor rewrites return a resource body without running the usual
    ``field_map``. Call this after rewriting URIs when
    ``normalization.ensure_gofish_compat`` is enabled so collector-facing JSON
    matches fully normalized resources.
    """

    if not enabled or not isinstance(body, dict):
        return
    if "PCIeFunction" not in (body.get("@odata.type") or ""):
        return
    if "ClassCode" in body:
        n = normalize_pci_class_code(body.get("ClassCode"))
        if isinstance(n, str):
            body["ClassCode"] = n
    # HPE Systems/PCIeDevices is a URL rewrite of the Chassis function, so this
    # body never goes through the PCIeFunction field map. iLO stores the NIC
    # firmware version in RevisionId; drop that and emit schema hex ids.
    # iLO also duplicates the ids under DeviceID / VendorID / Subsystem*ID.
    # No PCIeFunction schema defines those names.
    schema_ids = (
        ("DeviceId", 2),
        ("VendorId", 2),
        ("SubsystemId", 2),
        ("SubsystemVendorId", 2),
        ("RevisionId", 1),
    )
    nbytes_by_name = {key: nbytes for key, nbytes in schema_ids}
    for key, nbytes in schema_ids:
        if key not in body:
            continue
        formatted = format_pci_id(body.get(key), nbytes)
        if formatted is None:
            body.pop(key, None)
        else:
            body[key] = formatted
    for alias, canonical in (
        ("DeviceID", "DeviceId"),
        ("VendorID", "VendorId"),
        ("SubsystemDeviceID", "SubsystemId"),
        ("SubsystemID", "SubsystemId"),
        ("SubsystemVendorID", "SubsystemVendorId"),
        ("RevisionID", "RevisionId"),
        ("FunctionID", "FunctionId"),
    ):
        if alias not in body:
            continue
        if canonical not in body:
            raw = body.get(alias)
            if canonical == "FunctionId":
                if isinstance(raw, int) and not isinstance(raw, bool):
                    body[canonical] = raw
            else:
                formatted = format_pci_id(raw, nbytes_by_name[canonical])
                if formatted is not None:
                    body[canonical] = formatted
        body.pop(alias, None)


def pci_id_to_int(value: Any) -> int | None:
    """Parse a PCI id to a 16-bit int.

    ``0x``-prefixed strings are hex. All-digit strings are decimal (iLO sends
    ``32902`` for 0x8086). Other strings are hex when they parse (``10de``).
    Ints are masked to 16 bits. Booleans and unparsable values give None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value & 0xFFFF
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if text.lower().startswith("0x"):
            return int(text[2:], 16) & 0xFFFF
        if text.isdigit():
            return int(text, 10) & 0xFFFF
        return int(text, 16) & 0xFFFF
    except ValueError:
        return None


def format_pci_id(value: Any, nbytes: int) -> Any:
    """Format a PCI id as ``0x`` plus ``nbytes`` of hex.

    ``nbytes`` is 2 for VendorId, DeviceId, SubsystemId, and SubsystemVendorId,
    and 1 for RevisionId. Decimal strings such as HPE's ``32902`` become
    ``0x8086``. A string that already matches the schema pattern is unchanged.
    Anything else, including version strings in RevisionId, becomes null.
    """
    pattern = _PCI_ID_PATTERN.get(nbytes)
    if pattern is None:
        return value
    if isinstance(value, str) and pattern.match(value.strip()):
        return value.strip()
    if isinstance(value, bool) or value is None:
        return None
    number: int | None = None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        try:
            if text.lower().startswith("0x"):
                number = int(text, 16)
            elif text.isdigit():
                number = int(text, 10)
        except ValueError:
            number = None
    if number is None or number < 0 or number >= 1 << (nbytes * 8):
        return None
    return f"0x{number:0{nbytes * 2}X}"
