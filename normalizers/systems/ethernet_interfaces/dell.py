# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell System EthernetInterface: enrich from Chassis OEM DellNetworkAttributes.

Fetches ``.../Oem/Dell/DellNetworkAttributes/{id}`` once per interface and maps
useful ``Attributes`` fields onto standard EthernetInterface properties so
redfish-inventory-exporter (``redfish_network``) sees them without OEM-specific Go code.

When ``Status.Health`` / ``Status.State`` are missing or ``Unknown``, prefetch
matches the interface to a chassis ``PCIeFunction`` via ``Links.EthernetInterfaces``
and merges that (or the parent ``PCIeDevice``) ``Status`` so ``redfish_network_*``
health/state align with ``redfish_pcie_device_*``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from normalizers._shared.dell_pcie_inventory import (
    load_chassis_pcie_inventory,
    match_ethernet_status,
)
from normalizers._shared.dell_link_status import canonicalize_dell_oem_link_status
from normalizers._shared.status_fields import (
    status_field_unknown_or_empty,
    status_needs_pcie_fill,
)
from normalizers.chassis.network_ports.base import canonicalize_ethernet_link_status
from redpool.redfish_client import redfish_get_json

from ...optional import omit_if_null
from ...types import NormalizationContext
from .base import BaseEthernetInterfaceNormalizer

# Raw Dell ``Attributes`` dict from DellNetworkAttributes (prefetch-only).
_DELL_OEM_ATTRS_KEY = "_dell_network_oem_attributes"
_DELL_PCIE_ETH_STATUS_KEY = "_dell_ethernet_pcie_status"

# Dell NetworkAdapter Id is the stable prefix before port/partition suffixes, e.g.
# NIC.Integrated.1-2-1 -> NIC.Integrated.1 ; NIC.Slot.3-1-1 -> NIC.Slot.3
_DELL_ETH_ADAPTER_ID = re.compile(r"^(NIC\.\w+\.\d+)(?:-\d+)+$")

_LNK_SPEED_MBPS = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*(tb|gb|mb|t|g|m)\s*bps")
_GENERIC_ETH_NAMES = frozenset(
    s.lower() for s in ("System Ethernet Interface", "Ethernet Interface")
)


def _oem_attrs(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_DELL_OEM_ATTRS_KEY)
    return raw if isinstance(raw, dict) else {}


def chassis_path_from_ethernet_links(data: Dict[str, Any]) -> Optional[str]:
    """Return Chassis @odata.id from EthernetInterface Links, or None."""
    links = data.get("Links")
    if not isinstance(links, dict):
        return None
    ch = links.get("Chassis")
    if isinstance(ch, dict):
        oid = ch.get("@odata.id")
        if isinstance(oid, str) and "/Chassis/" in oid:
            return oid
    return None


def dell_network_adapter_id_from_ethernet_id(eth_id: str) -> Optional[str]:
    if not eth_id.startswith("NIC."):
        return None
    m = _DELL_ETH_ADAPTER_ID.match(eth_id)
    return m.group(1) if m else None


def dell_lnk_speed_to_speed_mbps(value: Any) -> Optional[int]:
    """Parse Dell ``LnkSpeed`` strings (e.g. ``25Gbps``) to integer Mbps."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or re.match(r"(?i)^(autoneg|auto|unknown|n/?a|-+)$", s):
        return None
    m = _LNK_SPEED_MBPS.search(s)
    if not m:
        return None
    try:
        num = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2).lower()
    if unit in ("t", "tb"):
        return int(num * 1_000_000)
    if unit in ("g", "gb"):
        return int(num * 1000)
    if unit in ("m", "mb"):
        return int(num)
    return None


def _speed_mbps_from_payload(ctx: NormalizationContext) -> Any:
    return ctx.data.get("SpeedMbps")


def _speed_mbps_missing_or_zero(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, str) and not raw.strip():
        return True
    if isinstance(raw, (int, float)) and raw == 0:
        return True
    return False


def effective_ethernet_link_status(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("LinkStatus")
    if raw is not None and str(raw).strip() != "":
        return canonicalize_ethernet_link_status(raw)
    mapped = canonicalize_dell_oem_link_status(_oem_attrs(ctx).get("LinkStatus"))
    if mapped:
        return mapped
    return canonicalize_ethernet_link_status(raw)


def effective_ethernet_speed_mbps(ctx: NormalizationContext) -> Any:
    raw = _speed_mbps_from_payload(ctx)
    if not _speed_mbps_missing_or_zero(raw):
        return raw
    parsed = dell_lnk_speed_to_speed_mbps(_oem_attrs(ctx).get("LnkSpeed"))
    if parsed is not None:
        return parsed
    return raw


def effective_ethernet_name(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Name")
    if isinstance(raw, str):
        t = raw.strip()
        if t and t.lower() not in _GENERIC_ETH_NAMES:
            return raw
    elif raw is not None:
        return raw
    dev = _oem_attrs(ctx).get("DeviceName")
    if isinstance(dev, str) and dev.strip():
        return dev.strip()
    return raw


def effective_ethernet_description(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Description")
    if isinstance(raw, str) and raw.strip():
        return raw
    attrs = _oem_attrs(ctx)
    for key in ("DeviceName", "ChipMdl"):
        v = attrs.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return raw


def _blank_to_null(raw: Any) -> Any:
    """Schema MAC patterns reject "", so an unknown MAC is null."""
    return None if isinstance(raw, str) and not raw.strip() else raw


def effective_ethernet_mac_address(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("MACAddress")
    if isinstance(raw, str) and raw.strip():
        return raw
    mac = _oem_attrs(ctx).get("MacAddr")
    if isinstance(mac, str) and mac.strip():
        return mac.strip()
    return _blank_to_null(raw)


def effective_ethernet_permanent_mac_address(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("PermanentMACAddress")
    if isinstance(raw, str) and raw.strip():
        return raw
    mac = _oem_attrs(ctx).get("MacAddr")
    if isinstance(mac, str) and mac.strip():
        return mac.strip()
    return _blank_to_null(raw)


def _pcie_eth_status_overlay(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_DELL_PCIE_ETH_STATUS_KEY)
    return raw if isinstance(raw, dict) else {}


def effective_ethernet_status(ctx: NormalizationContext) -> Any:
    """Merge chassis PCIe ``Status`` when BMC ``Status`` is missing or ``Unknown``."""
    raw = ctx.data.get("Status")
    base: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    overlay = _pcie_eth_status_overlay(ctx)
    out = dict(base)
    for key in ("Health", "State", "HealthRollup"):
        if key not in overlay:
            continue
        nv = overlay[key]
        if nv is None or (isinstance(nv, str) and not str(nv).strip()):
            continue
        if not status_field_unknown_or_empty(out.get(key)):
            continue
        out[key] = nv
    return out if out else (raw if isinstance(raw, dict) else {})


def prefetch_dell_ethernet_pcie_status(ctx: NormalizationContext) -> None:
    ctx.prefetched.pop(_DELL_PCIE_ETH_STATUS_KEY, None)
    if ctx.client is None:
        return
    if not status_needs_pcie_fill(ctx.data.get("Status")):
        return
    eth_odata_id = ctx.odata_id
    if not isinstance(eth_odata_id, str):
        return
    chassis_path = chassis_path_from_ethernet_links(ctx.data)
    if not chassis_path:
        return
    st = match_ethernet_status(
        load_chassis_pcie_inventory(ctx, chassis_path), eth_odata_id
    )
    if st:
        ctx.prefetched[_DELL_PCIE_ETH_STATUS_KEY] = st


def effective_ethernet_auto_neg(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("AutoNeg")
    if raw is not None:
        return raw
    lnk = _oem_attrs(ctx).get("LnkSpeed")
    if isinstance(lnk, str) and "autoneg" in lnk.lower():
        return True
    return raw


class DellSystemEthernetInterfaceNormalizer(BaseEthernetInterfaceNormalizer):
    """Prefetch Chassis DellNetworkAttributes and merge into standard fields."""

    def prefetch(self, ctx: NormalizationContext) -> None:
        ctx.prefetched.pop(_DELL_OEM_ATTRS_KEY, None)
        ctx.prefetched.pop(_DELL_PCIE_ETH_STATUS_KEY, None)
        if ctx.client is None:
            return
        eth_id = ctx.data.get("Id")
        if not isinstance(eth_id, str):
            return
        chassis_path = chassis_path_from_ethernet_links(ctx.data)
        if not chassis_path:
            return
        adapter_id = dell_network_adapter_id_from_ethernet_id(eth_id)
        if not adapter_id:
            prefetch_dell_ethernet_pcie_status(ctx)
            return
        na_path = (
            f"{chassis_path}/NetworkAdapters/{adapter_id}/NetworkDeviceFunctions/"
            f"{eth_id}/Oem/Dell/DellNetworkAttributes/{eth_id}"
        )
        payload = redfish_get_json(ctx.client, na_path)
        if not payload:
            prefetch_dell_ethernet_pcie_status(ctx)
            return
        attrs = payload.get("Attributes")
        if isinstance(attrs, dict) and attrs:
            ctx.prefetched[_DELL_OEM_ATTRS_KEY] = attrs
        prefetch_dell_ethernet_pcie_status(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Name"] = effective_ethernet_name
        m["Description"] = omit_if_null(effective_ethernet_description)
        m["MACAddress"] = effective_ethernet_mac_address
        m["PermanentMACAddress"] = effective_ethernet_permanent_mac_address
        m["LinkStatus"] = omit_if_null(effective_ethernet_link_status)
        m["SpeedMbps"] = effective_ethernet_speed_mbps
        m["AutoNeg"] = effective_ethernet_auto_neg
        m["Status"] = effective_ethernet_status
        return m
