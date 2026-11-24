# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""The NIC model Dell reports in ``Oem.Dell.DellNIC.ProductName``.

A NetworkDeviceFunction carries the adapter's product name here, and it is the only
model name for adapters that have no PCIe function (for example an embedded LOM).
iDRAC writes it as "<product> - <MAC>", and on some models the value is only a MAC.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, Optional

from redpool.redfish_client import redfish_get_json

_LOG = logging.getLogger(__name__)
_MAC = r"[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}"
_MAC_ONLY_RE = re.compile(f"^{_MAC}$")
_MAC_SUFFIX_RE = re.compile(rf"\s+-\s+{_MAC}\s*$")


def clean_nic_product_name(raw: Any) -> Optional[str]:
    """The product in ``ProductName`` without its ``- <MAC>`` suffix, or None.

    A value that is only a MAC address is not a name.
    """
    if not isinstance(raw, str):
        return None
    name = _MAC_SUFFIX_RE.sub("", raw).strip()
    if not name or _MAC_ONLY_RE.match(name):
        return None
    return name


def nic_fields(
    client: Any, function_paths: Iterable[str], wanted: Iterable[str]
) -> Dict[str, str]:
    """First usable ``DellNIC`` ``ProductName`` and ``VendorName`` among the functions.

    Only the keys in ``wanted`` are read, and the walk stops once all of them are found.
    A function that cannot be read is skipped: these are optional enrichments, and
    an error must not discard the document they would have enriched.
    """
    pending = set(wanted)
    found: Dict[str, str] = {}
    for path in function_paths:
        if not pending:
            break
        try:
            body = redfish_get_json(client, path)
        except Exception:
            _LOG.debug("NetworkDeviceFunction %s unavailable", path, exc_info=True)
            continue
        dell_nic = ((body.get("Oem") or {}).get("Dell") or {}).get("DellNIC")
        if not isinstance(dell_nic, dict):
            continue
        if "ProductName" in pending:
            name = clean_nic_product_name(dell_nic.get("ProductName"))
            if name:
                found["ProductName"] = name
                pending.discard("ProductName")
        if "VendorName" in pending:
            vendor = dell_nic.get("VendorName")
            if isinstance(vendor, str) and vendor.strip():
                found["VendorName"] = vendor.strip()
                pending.discard("VendorName")
    return found


def nic_product_name(client: Any, function_paths: Iterable[str]) -> Optional[str]:
    """First usable ``DellNIC.ProductName`` among the NetworkDeviceFunctions."""
    return nic_fields(client, function_paths, ("ProductName",)).get("ProductName")
