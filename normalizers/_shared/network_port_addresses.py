# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Shared helpers for Redfish NetworkPort address fields."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def mac_list_from_ethernet_associated(data: Dict[str, Any]) -> Optional[List[str]]:
    """Return cleaned ``Ethernet.AssociatedMACAddresses`` strings, or None if absent."""
    eth = data.get("Ethernet")
    if not isinstance(eth, dict):
        return None
    macs = eth.get("AssociatedMACAddresses")
    if not isinstance(macs, list):
        return None
    cleaned = [m.strip() for m in macs if isinstance(m, str) and m.strip()]
    return cleaned or None


def associated_network_addresses_present(data: Dict[str, Any]) -> bool:
    """True when ``AssociatedNetworkAddresses`` has at least one non-empty string."""
    raw = data.get("AssociatedNetworkAddresses")
    return isinstance(raw, list) and any(isinstance(m, str) and m.strip() for m in raw)
