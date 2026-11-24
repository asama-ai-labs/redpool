# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

from __future__ import annotations

import re
from typing import Optional

# BMC / FRU tokens on PowerSupply.Manufacturer → canonical OEM names.
_POWER_SUPPLY_MANUFACTURER_ALIASES: dict[str, str] = {
    "GREA": "Great Wall Power Technology Company Limited",
    "ACBE": "Acbel Polytech Inc.",
    "ACBEL": "Acbel Polytech Inc.",
    "DELL": "Dell Inc.",
    "DELTA": "Delta Electronics, Inc.",
    "DETA": "Delta Electronics, Inc.",
    "LTEON": "Lite-On Technology Corporation",
    "LTON": "Lite-On Technology Corporation",
    "CHCNY": "Chicony Power Technology Co., Ltd.",
}


def normalize_power_supply_manufacturer(raw: Optional[str]) -> Optional[str]:
    """Map PSU ``Manufacturer`` tokens (ODM / truncated FRU) to canonical names."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw  # type: ignore[return-value]
    s = raw.strip()
    if not s:
        return None
    mapped = _POWER_SUPPLY_MANUFACTURER_ALIASES.get(s.upper())
    if mapped is not None:
        return mapped
    return normalize_vendor_id(s)


# Server vendor names as BMCs send them (ServiceRoot.Vendor, or the first Oem key) →
# the one name normalizers register under. Lookup is case-insensitive.
_SERVER_VENDOR_ALIASES: dict[str, str] = {
    "dell": "Dell",
    "dell inc.": "Dell",
    "dell inc": "Dell",
    "dell technologies": "Dell",
    "hpe": "HPE",
    "hp": "HPE",
    "hpe inc.": "HPE",
    "hpe, inc.": "HPE",
    "hpe, inc": "HPE",
    "hpeilo": "HPE",
    "hewlett packard enterprise": "HPE",
    "hewlett-packard enterprise": "HPE",
    "lenovo": "Lenovo",
    "lenovo group": "Lenovo",
    "lenovo group limited": "Lenovo",
    "supermicro": "Supermicro",
    "super micro": "Supermicro",
    "supermicro computer": "Supermicro",
    "supermicro computer, inc.": "Supermicro",
    "supermicro computer inc.": "Supermicro",
    "super micro computer": "Supermicro",
    "super micro computer, inc.": "Supermicro",
    "intel": "Intel",
    "intel corporation": "Intel",
    "intel(r) corporation": "Intel",
}


def canonical_server_vendor(vendor: Optional[str]) -> str:
    """Canonical server vendor key (``Dell``, ``HPE``, ``Lenovo``, ``Supermicro``, ``Intel``).

    ``register_resource`` and the proxy lookup both go through this, so "Dell Inc.", "Hpe"
    and "Intel Corporation" reach the same vendor normalizers. An unrecognized vendor is
    returned stripped, and falls back to the base normalizer.
    """
    stripped = (vendor or "").strip()
    return _SERVER_VENDOR_ALIASES.get(stripped.casefold(), stripped)


def normalize_vendor_id(vendor_string: Optional[str]) -> Optional[str]:
    """Normalize vendor / manufacturer names to canonical forms."""
    if not vendor_string:
        return vendor_string

    trimmed = vendor_string.strip()
    vendor_lower = trimmed.lower()

    if "intel" in vendor_lower:
        return "Intel(R) Corporation"
    elif vendor_lower == "amd" or "advanced micro devices" in vendor_lower:
        return "Advanced Micro Devices, Inc."
    elif "nvidia" in vendor_lower:
        return "Nvidia Corporation"
    elif "ampere" in vendor_lower:
        return "Ampere(R) Computing"
    elif "micron" in vendor_lower:
        return "Micron Technology"
    elif "samsung" in vendor_lower:
        return "Samsung Electronics Co., Ltd."
    return vendor_string


# Maker implied by a model name's product line, for example "HPE Smart Array E208i-a"
# or the Dell backplane name "BP14G+ 0:1". Only leading product-line tokens match, so a
# bare part number never does. Every result is read from the payload's own model string.
_MODEL_MANUFACTURER_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"^(HPE|Hewlett Packard Enterprise)\b|\b(ProLiant|Smart Array|Smart Storage|MSA)\b",
            re.IGNORECASE,
        ),
        "HPE",
    ),
    (
        re.compile(
            r"^(Dell|PowerEdge|PowerVault)\b|\b(PERC|iDRAC)\b|^BP(\d+G|_)",
            re.IGNORECASE,
        ),
        "Dell",
    ),
    (
        re.compile(r"^(Lenovo|ThinkSystem|ThinkEdge|ThinkAgile)\b", re.IGNORECASE),
        "Lenovo",
    ),
    (
        re.compile(
            r"^(Supermicro|SuperServer|SYS|AS|SBI|SBA|BPN|PWS)[- ]", re.IGNORECASE
        ),
        "Supermicro",
    ),
)


MANUFACTURER_DISPLAY_NAMES: dict[str, str] = {"Dell": "Dell Inc."}


def manufacturer_display_name(vendor: str) -> str:
    """Name a canonical vendor key carries in a ``Manufacturer`` property."""
    return MANUFACTURER_DISPLAY_NAMES.get(vendor, vendor)


def manufacturer_from_model(model: Optional[str]) -> Optional[str]:
    """Canonical maker named by a model string's product line, or None when it names none."""
    if not isinstance(model, str):
        return None
    text = model.strip()
    if not text:
        return None
    for pattern, manufacturer in _MODEL_MANUFACTURER_RULES:
        if pattern.search(text):
            return manufacturer_display_name(manufacturer)
    return None


def manufacturer_from_storage_model(model: str) -> Optional[str]:
    """Map model string substrings to canonical OEM names (SSD inventory)."""
    ml = model.lower()
    if "intel" in ml:
        return "Intel(R) Corporation"
    if "samsung" in ml:
        return "Samsung Electronics Co., Ltd."
    if "micron" in ml:
        return "Micron Technology"
    return None


def normalize_drive_manufacturer(
    manufacturer: Optional[str], model: Optional[str]
) -> Optional[str]:
    """Normalize Drive ``Manufacturer``, inferring OEM when BMC reports generic ``ATA``."""
    out = normalize_vendor_id(manufacturer)
    if not model or out is None:
        return out
    if out.strip().lower() != "ata":
        return out
    inferred = manufacturer_from_storage_model(model)
    return inferred if inferred is not None else out
