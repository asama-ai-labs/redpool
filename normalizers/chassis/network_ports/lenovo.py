# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo Chassis NetworkPort: ``#Port`` quirks for gofish ``NetworkPort``.

- **PhysicalPortNumber**: Often only under ``Oem.Lenovo``; we promote it to the
  standard property. Fallback: parse ``Name`` (XCC typo ``Phyical Port N``) or
  numeric ``Id``.
- **CurrentLinkSpeedMbps**: DMTF ``#Port`` exposes ``CurrentSpeedGbps`` while
  ``NetworkPort`` / clients expect ``CurrentLinkSpeedMbps``; we convert Gbps→Mbps
  when the latter is missing or zero.
- **AssociatedNetworkAddresses**: ``Ethernet.MACAddress`` (NetworkDeviceFunction)
  is mirrored by Lenovo XCC onto the port itself as ``Oem.Lenovo.PhysicalPortMacAddress``
  (``#Port``) — we promote that (or DMTF ``Ethernet.AssociatedMACAddresses``) to the
  standard ``NetworkPort`` field when the backend didn't already set it. If neither is
  present on the port, we fall back to a prefetch join against the linked
  ``NetworkDeviceFunction``'s ``Ethernet.MACAddress`` / ``Oem.Lenovo.PhysicalPortMacAddress``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from redpool.redfish_client import redfish_get_json

from ..._shared.network_port_addresses import (
    associated_network_addresses_present,
    mac_list_from_ethernet_associated,
)
from ...types import NormalizationContext
from .base import BaseNetworkPortNormalizer


def _physical_port_number_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value == value
    return True


def _coerce_physical_port_string(value: Any) -> Any:
    if not _physical_port_number_nonempty(value):
        return value
    if isinstance(value, (int, float)) and value == int(value):
        return str(int(value))
    if isinstance(value, str):
        return value.strip()
    return value


def _int_port_hint(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if value.is_integer() and value >= 0:
            return int(value)
        return None
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return int(s, 10)
    return None


def _physical_port_from_name(name: Any) -> Optional[int]:
    if not isinstance(name, str):
        return None
    m = re.search(
        r"(?i)(?:ethernet|physical|phyical)\s+port\s+(\d+)",
        name,
    )
    if m:
        return int(m.group(1), 10)
    return None


def _lenovo_oem_physical_port_number(data: Dict[str, Any]) -> Any:
    oem = data.get("Oem")
    if not isinstance(oem, dict):
        return None
    lnv = oem.get("Lenovo")
    if not isinstance(lnv, dict):
        return None
    return lnv.get("PhysicalPortNumber")


def effective_lenovo_network_port_physical_port_number(
    ctx: NormalizationContext,
) -> Any:
    raw = ctx.data.get("PhysicalPortNumber")
    if _physical_port_number_nonempty(raw):
        return _coerce_physical_port_string(raw)

    oem_pn = _lenovo_oem_physical_port_number(ctx.data)
    if _physical_port_number_nonempty(oem_pn):
        return _coerce_physical_port_string(oem_pn)

    for candidate in (
        _physical_port_from_name(ctx.data.get("Name")),
        _int_port_hint(ctx.data.get("Id")),
    ):
        if candidate is not None:
            return str(candidate)

    return raw


def _current_link_speed_mbps_missing_or_zero(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, str) and not raw.strip():
        return True
    if isinstance(raw, (int, float)) and raw == 0:
        return True
    return False


def _current_speed_gbps_to_mbps(gbps: Any) -> Optional[int]:
    if gbps is None or isinstance(gbps, bool):
        return None
    try:
        f = float(gbps)
    except (TypeError, ValueError):
        return None
    if f < 0:
        return None
    return int(round(f * 1000))


def effective_lenovo_network_port_current_link_speed_mbps(
    ctx: NormalizationContext,
) -> Any:
    raw = ctx.data.get("CurrentLinkSpeedMbps")
    if not _current_link_speed_mbps_missing_or_zero(raw):
        return raw
    mbps = _current_speed_gbps_to_mbps(ctx.data.get("CurrentSpeedGbps"))
    if mbps is not None:
        return mbps
    return raw


def _canonicalize_mac_address(mac: str) -> str:
    """Normalize MAC strings to colon-separated uppercase octets (6 or 8 bytes)."""
    s = mac.strip()
    if not s:
        return s
    if ":" in s:
        parts = [p for p in s.split(":") if p]
        if len(parts) in (6, 8) and all(1 <= len(p) <= 2 for p in parts):
            try:
                return ":".join(f"{int(p, 16):02X}" for p in parts)
            except ValueError:
                return s
    hex_only = re.sub(r"[^0-9A-Fa-f]", "", s)
    if len(hex_only) in (12, 16) and len(hex_only) % 2 == 0:
        return ":".join(hex_only[i : i + 2].upper() for i in range(0, len(hex_only), 2))
    return s


def _canonicalize_mac_addresses(macs: List[str]) -> List[str]:
    return [
        _canonicalize_mac_address(m) for m in macs if isinstance(m, str) and m.strip()
    ]


def _mac_from_lenovo_oem(data: Dict[str, Any]) -> Optional[str]:
    oem = data.get("Oem")
    if not isinstance(oem, dict):
        return None
    lnv = oem.get("Lenovo")
    if not isinstance(lnv, dict):
        return None
    mac = lnv.get("PhysicalPortMacAddress")
    if isinstance(mac, str) and mac.strip():
        return mac.strip()
    return None


_NDF_LINK_LIST_KEYS = ("NetDevFuncMaxBWAlloc", "FunctionMaxBandwidth")
_NDF_MAC_PREFETCH_KEY = "_lenovo_network_port_ndf_mac"


def _network_device_function_odata_ids(data: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for key in _NDF_LINK_LIST_KEYS:
        entries = data.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ndf = entry.get("NetworkDeviceFunction")
            if isinstance(ndf, dict):
                oid = ndf.get("@odata.id")
                if isinstance(oid, str) and oid.strip():
                    ids.append(oid.strip())
    return ids


def _mac_from_network_device_function_json(ndf: Any) -> Optional[str]:
    if not isinstance(ndf, dict):
        return None
    eth = ndf.get("Ethernet")
    if isinstance(eth, dict):
        mac = eth.get("MACAddress")
        if isinstance(mac, str) and mac.strip():
            return mac.strip()
    return _mac_from_lenovo_oem(ndf)


def prefetch_lenovo_network_port_ndf_mac(ctx: NormalizationContext) -> None:
    """Join the linked NetworkDeviceFunction's MAC when the port has none of its own."""
    ctx.prefetched.pop(_NDF_MAC_PREFETCH_KEY, None)
    if ctx.client is None:
        return
    if (
        _mac_from_lenovo_oem(ctx.data)
        or mac_list_from_ethernet_associated(ctx.data)
        or associated_network_addresses_present(ctx.data)
    ):
        return
    for odata_id in _network_device_function_odata_ids(ctx.data):
        ndf = redfish_get_json(ctx.client, odata_id)
        mac = _mac_from_network_device_function_json(ndf)
        if mac:
            ctx.prefetched[_NDF_MAC_PREFETCH_KEY] = mac
            return


def effective_lenovo_network_port_associated_network_addresses(
    ctx: NormalizationContext,
) -> Any:
    raw = ctx.data.get("AssociatedNetworkAddresses")
    if associated_network_addresses_present(ctx.data):
        return _canonicalize_mac_addresses(
            [m.strip() for m in raw if isinstance(m, str) and m.strip()]
        )
    mac = _mac_from_lenovo_oem(ctx.data)
    if mac:
        return [_canonicalize_mac_address(mac)]
    macs = mac_list_from_ethernet_associated(ctx.data)
    if macs:
        return _canonicalize_mac_addresses(macs)
    prefetched = ctx.prefetched.get(_NDF_MAC_PREFETCH_KEY) if ctx.prefetched else None
    if isinstance(prefetched, str) and prefetched:
        return [_canonicalize_mac_address(prefetched)]
    return raw


class LenovoChassisNetworkPortNormalizer(BaseNetworkPortNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_lenovo_network_port_ndf_mac(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["PhysicalPortNumber"] = effective_lenovo_network_port_physical_port_number
        m["CurrentLinkSpeedMbps"] = (
            effective_lenovo_network_port_current_link_speed_mbps
        )
        m["AssociatedNetworkAddresses"] = (
            effective_lenovo_network_port_associated_network_addresses
        )
        return m
