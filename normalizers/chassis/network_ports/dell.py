# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell Chassis NetworkPort: enrich from NetworkDeviceFunctions DellNetworkAttributes.

When ``LinkStatus`` / ``CurrentLinkSpeedMbps`` / ``Name`` are empty or generic on
``Chassis/.../NetworkAdapters/{adapter}/NetworkPorts/{port}``, prefetch
``.../NetworkDeviceFunctions/{port}/Oem/Dell/DellNetworkAttributes/{port}`` and
map ``Attributes`` (same document used for Systems EthernetInterfaces).

When ``Status.Health`` / ``Status.State`` are missing or ``Unknown``, merge
``Status`` from the chassis ``PCIeFunction`` (or parent ``PCIeDevice``) linked to
the port so ``redfish_network_port_*`` aligns with ``redfish_pcie_device_*``.

Some Dell BMCs set ``PhysicalPortNumber`` to the **PCIe slot** (e.g. ``3``) for
every port on ``NIC.Slot.3``; when that matches the slot ordinal we rewrite from
the port ``Id`` suffix (``NIC.Slot.3-1`` → ``1``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from normalizers._shared.dell_link_status import canonicalize_dell_oem_link_status
from normalizers._shared.dell_pcie_inventory import (
    load_chassis_pcie_inventory,
    match_port_display,
    match_port_status,
    slot_ordinal_from_network_adapter_id,
)
from normalizers._shared.status_fields import (
    status_field_unknown_or_empty,
    status_needs_pcie_fill,
)
from normalizers.systems.ethernet_interfaces.dell import dell_lnk_speed_to_speed_mbps
from normalizers.types import NormalizationContext
from redpool.redfish_client import redfish_get_json

from ...optional import omit_if_null
from .base import (
    BaseNetworkPortNormalizer,
    canonicalize_network_port_link_status,
)

_DELL_OEM_ATTRS_KEY = "_dell_network_port_oem_attributes"
_DELL_PORT_PCIE_DISPLAY_KEY = "_dell_network_port_pcie_display"
_DELL_PORT_PCIE_STATUS_KEY = "_dell_network_port_pcie_status"

GENERIC_PORT_NAMES = frozenset(
    s.lower()
    for s in (
        "Network Port View",
        "Network Port",
        "Port",
        "Network Inteface Card(NIC) Port View",
    )
)


def parse_chassis_network_port_path(
    odata_id: str,
) -> Optional[Tuple[str, str, str]]:
    """Return ``(chassis_prefix, adapter_id, port_id)`` from a NetworkPort or Port ``@odata.id``."""
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


def oem_attrs(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_DELL_OEM_ATTRS_KEY)
    return raw if isinstance(raw, dict) else {}


def _name_needs_pcie_fill(raw: Any) -> bool:
    if not isinstance(raw, str) or not raw.strip():
        return True
    return raw.strip().lower() in GENERIC_PORT_NAMES


def _pcie_port_display(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_DELL_PORT_PCIE_DISPLAY_KEY)
    return raw if isinstance(raw, dict) else {}


def _pcie_port_status_overlay(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_DELL_PORT_PCIE_STATUS_KEY)
    return raw if isinstance(raw, dict) else {}


def prefetch_network_port_pcie_status(ctx: NormalizationContext) -> None:
    """Fill ``Status`` from chassis PCIe when the port reports ``Unknown`` / empty."""
    ctx.prefetched.pop(_DELL_PORT_PCIE_STATUS_KEY, None)
    if ctx.client is None:
        return
    if not status_needs_pcie_fill(ctx.data.get("Status")):
        return
    port_id = ctx.data.get("Id")
    if not isinstance(port_id, str):
        return
    parsed = parse_chassis_network_port_path(ctx.odata_id)
    if not parsed:
        return
    chassis_prefix, _adapter_id, path_port_id = parsed
    if path_port_id != port_id:
        return
    st = match_port_status(load_chassis_pcie_inventory(ctx, chassis_prefix), port_id)
    if st:
        ctx.prefetched[_DELL_PORT_PCIE_STATUS_KEY] = st


def prefetch_network_port_pcie_display(ctx: NormalizationContext) -> None:
    """Fill ``Name`` from chassis PCIeFunction when BMC shows placeholders."""
    ctx.prefetched.pop(_DELL_PORT_PCIE_DISPLAY_KEY, None)
    if ctx.client is None:
        return
    if not _name_needs_pcie_fill(ctx.data.get("Name")):
        return
    port_id = ctx.data.get("Id")
    if not isinstance(port_id, str):
        return
    parsed = parse_chassis_network_port_path(ctx.odata_id)
    if not parsed:
        return
    chassis_prefix, _adapter_id, path_port_id = parsed
    if path_port_id != port_id:
        return
    disp = match_port_display(load_chassis_pcie_inventory(ctx, chassis_prefix), port_id)
    if disp:
        ctx.prefetched[_DELL_PORT_PCIE_DISPLAY_KEY] = disp


def prefetch_dell_network_port_oem(ctx: NormalizationContext) -> None:
    ctx.prefetched.pop(_DELL_OEM_ATTRS_KEY, None)
    if ctx.client is None:
        return
    port_id = ctx.data.get("Id")
    if not isinstance(port_id, str):
        return
    parsed = parse_chassis_network_port_path(ctx.odata_id)
    if not parsed:
        return
    _chassis_prefix, adapter_id, path_port_id = parsed
    if path_port_id != port_id:
        return
    na_path = (
        f"{_chassis_prefix}/NetworkAdapters/{adapter_id}/NetworkDeviceFunctions/"
        f"{port_id}/Oem/Dell/DellNetworkAttributes/{port_id}"
    )
    payload = redfish_get_json(ctx.client, na_path)
    if not payload:
        return
    attrs = payload.get("Attributes")
    if isinstance(attrs, dict) and attrs:
        ctx.prefetched[_DELL_OEM_ATTRS_KEY] = attrs


def _link_status_raw_missing_or_empty(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, str) and not raw.strip():
        return True
    return False


def _current_speed_missing_or_zero(raw: Any) -> bool:
    if raw is None:
        return True
    if isinstance(raw, str) and not raw.strip():
        return True
    if isinstance(raw, (int, float)) and raw == 0:
        return True
    return False


def effective_network_port_link_status(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("LinkStatus")
    if not _link_status_raw_missing_or_empty(raw):
        return canonicalize_network_port_link_status(raw)
    mapped = canonicalize_dell_oem_link_status(oem_attrs(ctx).get("LinkStatus"))
    if mapped:
        return canonicalize_network_port_link_status(mapped)
    return canonicalize_network_port_link_status(raw)


def effective_network_port_current_link_speed_mbps(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("CurrentLinkSpeedMbps")
    if not _current_speed_missing_or_zero(raw):
        return raw
    parsed = dell_lnk_speed_to_speed_mbps(oem_attrs(ctx).get("LnkSpeed"))
    if parsed is not None:
        return parsed
    return raw


def effective_network_port_name(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Name")
    if isinstance(raw, str):
        t = raw.strip()
        if t and t.lower() not in GENERIC_PORT_NAMES:
            return raw
    elif raw is not None:
        return raw
    dev = oem_attrs(ctx).get("DeviceName")
    if isinstance(dev, str) and dev.strip():
        return dev.strip()
    pc = _pcie_port_display(ctx).get("Name")
    if isinstance(pc, str) and pc.strip():
        return pc.strip()
    return raw


def port_number_from_id(ctx: NormalizationContext, raw: Any) -> Any:
    """Prefer the port index from *Id* when the BMC repeats the PCIe slot as the port number.

    ``raw`` is the BMC's value (``PhysicalPortNumber`` on a NetworkPort, ``PortId`` on a Port).
    """
    parsed = parse_chassis_network_port_path(ctx.odata_id)
    if not parsed:
        return raw
    _chassis, adapter_id, path_port_id = parsed
    port_id = ctx.data.get("Id")
    if not isinstance(port_id, str) or not isinstance(adapter_id, str):
        return raw
    if path_port_id != port_id:
        return raw
    slot_ord = slot_ordinal_from_network_adapter_id(adapter_id)
    if slot_ord is None:
        return raw
    raw_s = str(raw).strip() if raw is not None else ""
    if raw_s != str(slot_ord):
        return raw
    prefix = adapter_id + "-"
    if not port_id.startswith(prefix):
        return raw
    suffix = port_id[len(prefix) :]
    if suffix.isdigit():
        return suffix
    return raw


def effective_network_port_physical_port_number(ctx: NormalizationContext) -> Any:
    return port_number_from_id(ctx, ctx.data.get("PhysicalPortNumber"))


def effective_network_port_status(ctx: NormalizationContext) -> Any:
    """Merge chassis PCIe ``Status`` when BMC ``Status`` is missing or ``Unknown``."""
    raw = ctx.data.get("Status")
    base: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    overlay = _pcie_port_status_overlay(ctx)
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


class DellChassisNetworkPortNormalizer(BaseNetworkPortNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        ctx.prefetched.pop(_DELL_OEM_ATTRS_KEY, None)
        ctx.prefetched.pop(_DELL_PORT_PCIE_DISPLAY_KEY, None)
        ctx.prefetched.pop(_DELL_PORT_PCIE_STATUS_KEY, None)
        prefetch_dell_network_port_oem(ctx)
        prefetch_network_port_pcie_display(ctx)
        prefetch_network_port_pcie_status(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Status"] = effective_network_port_status
        m["LinkStatus"] = omit_if_null(effective_network_port_link_status)
        m["CurrentLinkSpeedMbps"] = effective_network_port_current_link_speed_mbps
        m["Name"] = effective_network_port_name
        m["PhysicalPortNumber"] = effective_network_port_physical_port_number
        return m
