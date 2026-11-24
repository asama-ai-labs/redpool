# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE Chassis NetworkPort: ``Status`` from OEM physical ports and chassis PCIe.

HPE adapters often expose ``#Port`` members under ``.../Ports/{id}`` while
clients use ``.../NetworkPorts/{id}`` (see
:mod:`normalizers.chassis.network_adapters.hpe_chassis_network_rewrite`).
When ``Status`` is missing or incomplete, merge ``Oem.Hpe.PhysicalPorts`` for the
matching ``PortNumber`` and adapter-level PCIe ``Status`` (same resolution as
:mod:`normalizers.chassis.network_adapters.hpe`).

HPE ``#Port`` resources frequently omit ``PhysicalPortNumber`` while supplying
``PortId`` (PHY index, may differ from member ``Id``). We populate
``PhysicalPortNumber`` from ``PortId``, ``Name`` (``Ethernet Port N``), ``Id``,
or OEM ``PhysicalPorts[].PortNumber`` when still unset.

``#Port`` members also expose ``CurrentSpeedGbps`` and
``Ethernet.AssociatedMACAddresses`` instead of ``NetworkPort`` fields. We promote
those to ``CurrentLinkSpeedMbps`` and ``AssociatedNetworkAddresses``. When the
port omits MAC, we join the linked ``NetworkDeviceFunction`` via
``Links.PhysicalNetworkPortAssignment`` (or ``AssignablePhysicalNetworkPorts``).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from redpool.redfish_client import redfish_get_json

from ..._shared.network_port_addresses import (
    associated_network_addresses_present,
    mac_list_from_ethernet_associated,
)
from ...types import NormalizationContext
from normalizers._shared.status_fields import (
    status_field_unknown_or_empty,
    status_needs_pcie_fill,
)
from ..network_adapters.hpe import resolve_hpe_adapter_pcie_status_overlay
from .base import BaseNetworkPortNormalizer

_HPE_PORT_OEM_STATUS_KEY = "_hpe_network_port_oem_status"
_HPE_PORT_PCIE_STATUS_KEY = "_hpe_network_port_pcie_status"
_HPE_PORT_PHYSICAL_NUMBER_KEY = "_hpe_network_port_physical_number"
_HPE_PORT_NDF_MAC_KEY = "_hpe_network_port_ndf_mac"


def parse_chassis_network_port_path(
    odata_id: str,
) -> Optional[Tuple[str, str, str]]:
    """Return ``(chassis_prefix, adapter_id, port_id)`` from a NetworkPort ``@odata.id``."""
    if not isinstance(odata_id, str):
        return None
    if "/NetworkAdapters/" not in odata_id:
        return None
    chassis_prefix, rest = odata_id.split("/NetworkAdapters/", 1)
    # A port is a member of NetworkPorts (deprecated) or Ports.
    for marker in ("/NetworkPorts/", "/Ports/"):
        if marker not in rest:
            continue
        adapter_id, port_id = rest.split(marker, 1)
        if "/" in adapter_id or "/" in port_id:
            return None
        return chassis_prefix, adapter_id, port_id
    return None


def _coerce_status_subset(st: Any) -> Dict[str, Any]:
    if not isinstance(st, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in ("Health", "State", "HealthRollup"):
        if k in st and st[k] is not None:
            out[k] = st[k]
    return out


def _physical_port_number_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value == value
    return True


def _int_port_hint(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
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
    m = re.search(r"(?i)ethernet\s+port\s+(\d+)", name)
    if m:
        return int(m.group(1), 10)
    return None


def _oem_physical_port_status(adapter: Dict[str, Any], port_id: str) -> Dict[str, Any]:
    oem = adapter.get("Oem")
    if not isinstance(oem, dict):
        return {}
    hpe = oem.get("Hpe") or oem.get("HPE") or {}
    if not isinstance(hpe, dict):
        return {}
    ports = hpe.get("PhysicalPorts")
    if not isinstance(ports, list):
        return {}
    try:
        want = int(str(port_id).strip(), 10)
    except ValueError:
        return {}
    for pp in ports:
        if not isinstance(pp, dict):
            continue
        raw_pn = pp.get("PortNumber")
        try:
            pn = int(raw_pn) if raw_pn is not None else -1
        except (TypeError, ValueError):
            continue
        if pn != want:
            continue
        return _coerce_status_subset(pp.get("Status"))
    return {}


def _oem_physical_port_number(adapter: Dict[str, Any], port_id: str) -> Optional[int]:
    oem = adapter.get("Oem")
    if not isinstance(oem, dict):
        return None
    hpe = oem.get("Hpe") or oem.get("HPE") or {}
    if not isinstance(hpe, dict):
        return None
    ports = hpe.get("PhysicalPorts")
    if not isinstance(ports, list):
        return None
    try:
        want = int(str(port_id).strip(), 10)
    except ValueError:
        return None
    for pp in ports:
        if not isinstance(pp, dict):
            continue
        raw_pn = pp.get("PortNumber")
        try:
            pn = int(raw_pn) if raw_pn is not None else -1
        except (TypeError, ValueError):
            continue
        if pn != want:
            continue
        return pn
    return None


def _infer_health_rollup_from_health(out: Dict[str, Any]) -> None:
    if not status_field_unknown_or_empty(out.get("HealthRollup")):
        return
    h = out.get("Health")
    if isinstance(h, str):
        t = h.strip()
        if t and t.casefold() != "unknown":
            out["HealthRollup"] = t


def prefetch_hpe_network_port_status(ctx: NormalizationContext) -> None:
    ctx.prefetched.pop(_HPE_PORT_OEM_STATUS_KEY, None)
    ctx.prefetched.pop(_HPE_PORT_PCIE_STATUS_KEY, None)
    ctx.prefetched.pop(_HPE_PORT_PHYSICAL_NUMBER_KEY, None)
    if ctx.client is None:
        return
    parsed = parse_chassis_network_port_path(ctx.odata_id)
    if not parsed:
        return
    needs_status = status_needs_pcie_fill(ctx.data.get("Status"))
    needs_phys = not _physical_port_number_nonempty(ctx.data.get("PhysicalPortNumber"))
    if not needs_status and not needs_phys:
        return
    chassis_prefix, adapter_id, port_id = parsed
    na_path = f"{chassis_prefix.rstrip('/')}/NetworkAdapters/{adapter_id}"
    na = redfish_get_json(ctx.client, na_path)
    if not isinstance(na, dict):
        return
    if needs_status:
        oem_st = _oem_physical_port_status(na, port_id)
        if oem_st:
            ctx.prefetched[_HPE_PORT_OEM_STATUS_KEY] = oem_st
        pcie_st = resolve_hpe_adapter_pcie_status_overlay(ctx.client, na)
        if pcie_st:
            ctx.prefetched[_HPE_PORT_PCIE_STATUS_KEY] = pcie_st
    if needs_phys:
        oem_pn = _oem_physical_port_number(na, port_id)
        if oem_pn is not None:
            ctx.prefetched[_HPE_PORT_PHYSICAL_NUMBER_KEY] = {
                "PhysicalPortNumber": str(oem_pn),
            }


def effective_hpe_network_port_status(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Status")
    base: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    out = dict(base)
    for key in ("Health", "State", "HealthRollup"):
        for pkey in (_HPE_PORT_OEM_STATUS_KEY, _HPE_PORT_PCIE_STATUS_KEY):
            overlay = ctx.prefetched.get(pkey)
            if not isinstance(overlay, dict) or key not in overlay:
                continue
            nv = overlay[key]
            if nv is None or (isinstance(nv, str) and not str(nv).strip()):
                continue
            if not status_field_unknown_or_empty(out.get(key)):
                continue
            out[key] = nv
    _infer_health_rollup_from_health(out)
    return out if out else (raw if isinstance(raw, dict) else {})


def effective_hpe_physical_port_number(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("PhysicalPortNumber")
    if _physical_port_number_nonempty(raw):
        # gofish NetworkPort uses string; JSON numbers break Unmarshal for this field.
        if isinstance(raw, (int, float)) and raw == int(raw):
            return str(int(raw))
        return raw
    for candidate in (
        _int_port_hint(ctx.data.get("PortId")),
        _physical_port_from_name(ctx.data.get("Name")),
        _int_port_hint(ctx.data.get("Id")),
    ):
        if candidate is not None:
            return str(candidate)
    overlay = ctx.prefetched.get(_HPE_PORT_PHYSICAL_NUMBER_KEY)
    if isinstance(overlay, dict) and "PhysicalPortNumber" in overlay:
        return overlay["PhysicalPortNumber"]
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


def effective_hpe_network_port_current_link_speed_mbps(
    ctx: NormalizationContext,
) -> Any:
    raw = ctx.data.get("CurrentLinkSpeedMbps")
    if not _current_link_speed_mbps_missing_or_zero(raw):
        return raw
    mbps = _current_speed_gbps_to_mbps(ctx.data.get("CurrentSpeedGbps"))
    if mbps is not None:
        return mbps
    return raw


def _mac_from_network_device_function_json(ndf: Any) -> Optional[str]:
    if not isinstance(ndf, dict):
        return None
    eth = ndf.get("Ethernet")
    if isinstance(eth, dict):
        mac = eth.get("MACAddress")
        if isinstance(mac, str) and mac.strip():
            return mac.strip()
    return None


def _port_assignment_matches(port_id: str, assign_id: str) -> bool:
    if not isinstance(assign_id, str) or not assign_id.strip():
        return False
    base = assign_id.rstrip("/")
    return base.endswith(f"/NetworkPorts/{port_id}") or base.endswith(
        f"/Ports/{port_id}"
    )


def _network_device_function_links_port(
    ndf: Dict[str, Any], port_id: str, port_odata_id: str
) -> bool:
    links = ndf.get("Links")
    if isinstance(links, dict):
        assign = links.get("PhysicalNetworkPortAssignment")
        if isinstance(assign, dict):
            oid = assign.get("@odata.id")
            if isinstance(oid, str) and (
                _port_assignment_matches(port_id, oid)
                or oid.rstrip("/") == port_odata_id.rstrip("/")
            ):
                return True
    assignable = ndf.get("AssignablePhysicalNetworkPorts")
    if isinstance(assignable, list):
        for entry in assignable:
            if not isinstance(entry, dict):
                continue
            oid = entry.get("@odata.id")
            if isinstance(oid, str) and (
                _port_assignment_matches(port_id, oid)
                or oid.rstrip("/") == port_odata_id.rstrip("/")
            ):
                return True
    return False


def prefetch_hpe_network_port_ndf_mac(ctx: NormalizationContext) -> None:
    """Join linked NetworkDeviceFunction MAC when the port has none of its own."""
    ctx.prefetched.pop(_HPE_PORT_NDF_MAC_KEY, None)
    if ctx.client is None:
        return
    if mac_list_from_ethernet_associated(
        ctx.data
    ) or associated_network_addresses_present(ctx.data):
        return
    parsed = parse_chassis_network_port_path(ctx.odata_id)
    if not parsed:
        return
    chassis_prefix, adapter_id, port_id = parsed
    ndf_coll_path = f"{chassis_prefix.rstrip('/')}/NetworkAdapters/{adapter_id}/NetworkDeviceFunctions"
    coll = redfish_get_json(ctx.client, ndf_coll_path)
    if not isinstance(coll, dict):
        return
    members = coll.get("Members") or []
    if not isinstance(members, list):
        return
    port_odata_id = ctx.odata_id.rstrip("/")
    for member in members:
        if not isinstance(member, dict):
            continue
        ndf_oid = member.get("@odata.id")
        if not isinstance(ndf_oid, str) or not ndf_oid.strip():
            continue
        ndf = redfish_get_json(ctx.client, ndf_oid.strip())
        if not isinstance(ndf, dict):
            continue
        if not _network_device_function_links_port(ndf, port_id, port_odata_id):
            continue
        mac = _mac_from_network_device_function_json(ndf)
        if mac:
            ctx.prefetched[_HPE_PORT_NDF_MAC_KEY] = mac
            return


def effective_hpe_network_port_associated_network_addresses(
    ctx: NormalizationContext,
) -> Any:
    raw = ctx.data.get("AssociatedNetworkAddresses")
    if associated_network_addresses_present(ctx.data):
        return [m.strip() for m in raw if isinstance(m, str) and m.strip()]
    macs = mac_list_from_ethernet_associated(ctx.data)
    if macs:
        return macs
    prefetched = ctx.prefetched.get(_HPE_PORT_NDF_MAC_KEY) if ctx.prefetched else None
    if isinstance(prefetched, str) and prefetched:
        return [prefetched]
    return raw


class HPEChassisNetworkPortNormalizer(BaseNetworkPortNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_hpe_network_port_status(ctx)
        prefetch_hpe_network_port_ndf_mac(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Status"] = effective_hpe_network_port_status
        m["PhysicalPortNumber"] = effective_hpe_physical_port_number
        m["CurrentLinkSpeedMbps"] = effective_hpe_network_port_current_link_speed_mbps
        m["AssociatedNetworkAddresses"] = (
            effective_hpe_network_port_associated_network_addresses
        )
        return m
