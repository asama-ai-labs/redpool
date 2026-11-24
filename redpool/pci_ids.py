# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""In-memory PCI ID database loader backed by third_party/pciids/pci.ids.

This provides lightweight helpers to map numeric PCI IDs to human-readable
names for vendors, devices, and subsystems. The file is parsed once on
first use and cached in-process.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

LOG = logging.getLogger("redpool.pci_ids")

_loaded = False
_pci_vendors: Dict[str, str] = {}
_pci_devices: Dict[str, Dict[str, str]] = {}
_pci_subsystems: Dict[str, Dict[str, str]] = {}


def _normalize_id(val: Optional[str]) -> Optional[str]:
    """Normalize a hex ID: strip 0x, lowercase, keep as 4+ hex chars."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if s.startswith("0x") or s.startswith("0X"):
        s = s[2:]
    return s.lower()


def _load_once() -> None:
    """Load pci.ids into memory once."""
    global _loaded
    if _loaded:
        return

    base = Path(__file__).resolve().parent.parent  # project root
    pci_ids_path = base / "third_party" / "pciids" / "pci.ids"
    if not pci_ids_path.is_file():
        LOG.info("PCI IDs file not found at %s; PCI name lookup disabled", pci_ids_path)
        _loaded = True
        return

    LOG.info("Loading PCI IDs from %s", pci_ids_path)
    vendors: Dict[str, str] = {}
    devices: Dict[str, Dict[str, str]] = {}
    subsystems: Dict[str, Dict[str, str]] = {}

    current_vendor: Optional[str] = None
    current_device: Optional[str] = None

    try:
        with pci_ids_path.open(encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue

                # Vendor line (no leading whitespace, not class section)
                if not line.startswith("\t") and not line.startswith("C "):
                    parts = line.split("  ", 1)
                    if len(parts) >= 2:
                        vid = _normalize_id(parts[0])
                        name = parts[1].strip()
                        if vid:
                            current_vendor = vid
                            current_device = None
                            vendors[vid] = name
                    continue

                # Device line (single tab)
                if line.startswith("\t") and not line.startswith("\t\t"):
                    line2 = line.lstrip("\t")
                    parts = line2.split("  ", 1)
                    if len(parts) >= 2 and current_vendor:
                        did = _normalize_id(parts[0])
                        name = parts[1].strip()
                        if did:
                            devs = devices.setdefault(current_vendor, {})
                            devs[did] = name
                            current_device = did
                    continue

                # Subsystem line (double tab)
                if line.startswith("\t\t"):
                    line2 = line.lstrip("\t")
                    parts = line2.split("  ", 1)
                    if len(parts) >= 2 and current_vendor and current_device:
                        subsys_id = parts[0].strip()
                        subsys_name = parts[1].strip()
                        key = f"{current_vendor}:{current_device}"
                        subs = subsystems.setdefault(key, {})
                        subsys_parts = subsys_id.split()
                        if len(subsys_parts) == 2:
                            svid = _normalize_id(subsys_parts[0])
                            sdid = _normalize_id(subsys_parts[1])
                            if svid and sdid:
                                subs[f"{svid}:{sdid}"] = subsys_name
                    continue
    except OSError as exc:
        LOG.warning("Failed to load PCI IDs from %s: %s", pci_ids_path, exc)
        _loaded = True
        return

    _pci_vendors.update(vendors)
    _pci_devices.update(devices)
    _pci_subsystems.update(subsystems)
    _loaded = True
    LOG.info(
        "Loaded PCI IDs: %d vendors, %d vendor-device pairs, %d subsystem entries",
        len(_pci_vendors),
        sum(len(d) for d in _pci_devices.values()),
        sum(len(s) for s in _pci_subsystems.values()),
    )


def lookup_pci_names(
    vendor_id: Optional[str],
    device_id: Optional[str] = None,
    subsys_vendor_id: Optional[str] = None,
    subsys_device_id: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Look up (vendor_name, device_name, subsystem_name) from PCI IDs.

    IDs may be integers or hex strings with or without 0x prefix.
    Returns None for any component that cannot be resolved.
    """
    _load_once()
    if not _loaded:
        return None, None, None

    v = _normalize_id(vendor_id)
    d = _normalize_id(device_id)
    sv = _normalize_id(subsys_vendor_id)
    sd = _normalize_id(subsys_device_id)

    vendor_name = _pci_vendors.get(v) if v else None

    device_name = None
    if v and d:
        devs = _pci_devices.get(v)
        if devs:
            device_name = devs.get(d)

    subsystem_name = None
    if v and d and sv and sd:
        key = f"{v}:{d}"
        subs = _pci_subsystems.get(key)
        if subs:
            subsystem_name = subs.get(f"{sv}:{sd}")

    return vendor_name, device_name, subsystem_name
