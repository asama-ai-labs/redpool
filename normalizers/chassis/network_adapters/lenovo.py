# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo Chassis NetworkAdapter: PCIe ``Status`` enrichment and ``Ports`` → ``NetworkPorts`` link.

Lenovo often omits ``Status.HealthRollup`` on ``NetworkAdapter`` while
``Controllers[].Links.PCIeDevices`` references the chassis ``PCIeDevice``.
Prefetch that device (or its first ``PCIeFunction``) and merge ``Health`` /
``State`` / ``HealthRollup``. When rollup is still unknown but ``Health`` is a
known value, set ``HealthRollup`` to ``Health``.

Some Lenovo BMCs expose only the ``Ports`` collection (``#Port``) while
``redfish-inventory-exporter`` walks ``NetworkPorts``. When ``NetworkPorts`` is
missing but ``Ports`` has ``@odata.id``, emit a ``NetworkPorts`` collection link
at the canonical path (fixtures may include ``NetworkPorts`` mirror files).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from redpool.redfish_client import redfish_get_json

from ...types import NormalizationContext
from .base import BaseNetworkAdapterNormalizer
from normalizers._shared.status_fields import (
    adapter_status_needs_pcie_fill,
    status_field_unknown_or_empty,
)

_LENOVO_PCIE_STATUS_KEY = "_lenovo_network_adapter_pcie_status"


def _coerce_status_subset(st: Any) -> Dict[str, Any]:
    if not isinstance(st, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in ("Health", "State", "HealthRollup"):
        if k in st and st[k] is not None:
            out[k] = st[k]
    return out


def lenovo_network_adapter_pcie_device_uris(data: Dict[str, Any]) -> List[str]:
    """Return ``@odata.id`` values from ``Controllers[].Links.PCIeDevices``."""
    uris: List[str] = []
    controllers = data.get("Controllers")
    if not isinstance(controllers, list):
        return uris
    for ctl in controllers:
        if not isinstance(ctl, dict):
            continue
        links = ctl.get("Links")
        if not isinstance(links, dict):
            continue
        arr = links.get("PCIeDevices")
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            oid = item.get("@odata.id")
            if isinstance(oid, str) and oid.strip():
                uris.append(oid.strip())
    return uris


def _status_from_pcie_resource(client: Any, pcie_uri: str) -> Optional[Dict[str, Any]]:
    """``Status`` subset from ``PCIeDevice`` or first member of its ``PCIeFunctions`` collection."""
    dev = redfish_get_json(client, pcie_uri)
    if not isinstance(dev, dict):
        return None
    st = _coerce_status_subset(dev.get("Status"))
    if st:
        return st
    link = dev.get("PCIeFunctions")
    if not isinstance(link, dict):
        return None
    coll_id = link.get("@odata.id")
    if not isinstance(coll_id, str) or not client:
        return None
    pfcoll = redfish_get_json(client, coll_id)
    pf_members = pfcoll.get("Members") if isinstance(pfcoll, dict) else None
    if not isinstance(pf_members, list):
        return None
    for pref in pf_members:
        if not isinstance(pref, dict):
            continue
        m_id = pref.get("@odata.id")
        if not isinstance(m_id, str):
            continue
        fn = redfish_get_json(client, m_id)
        if not isinstance(fn, dict):
            continue
        st_fn = _coerce_status_subset(fn.get("Status"))
        if st_fn:
            return st_fn
    return None


def prefetch_lenovo_network_adapter_pcie(ctx: NormalizationContext) -> None:
    """Prefetch PCIe ``Status`` from the first linked ``PCIeDevice``."""
    ctx.prefetched.pop(_LENOVO_PCIE_STATUS_KEY, None)
    if ctx.client is None:
        return
    if not adapter_status_needs_pcie_fill(ctx.data.get("Status")):
        return
    uris = lenovo_network_adapter_pcie_device_uris(ctx.data)
    if not uris:
        return
    st = _status_from_pcie_resource(ctx.client, uris[0])
    if st:
        ctx.prefetched[_LENOVO_PCIE_STATUS_KEY] = st


def _lenovo_pcie_status_overlay(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_LENOVO_PCIE_STATUS_KEY)
    return raw if isinstance(raw, dict) else {}


def _infer_health_rollup_from_health(out: Dict[str, Any]) -> None:
    if not status_field_unknown_or_empty(out.get("HealthRollup")):
        return
    h = out.get("Health")
    if isinstance(h, str):
        t = h.strip()
        if t and t.casefold() != "unknown":
            out["HealthRollup"] = t


def effective_lenovo_network_adapter_status(ctx: NormalizationContext) -> Any:
    """Merge PCIe ``Status``; infer ``HealthRollup`` from ``Health`` when still unknown."""
    raw = ctx.data.get("Status")
    base: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    overlay = _lenovo_pcie_status_overlay(ctx)
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
    _infer_health_rollup_from_health(out)
    return out if out else (raw if isinstance(raw, dict) else {})


def _first_controller_ports_member_uri(data: Dict[str, Any]) -> Optional[str]:
    """Return first ``Controllers[].Links.Ports[].@odata.id`` (…/Ports/{n}), if any."""
    controllers = data.get("Controllers")
    if not isinstance(controllers, list):
        return None
    for ctl in controllers:
        if not isinstance(ctl, dict):
            continue
        links = ctl.get("Links")
        if not isinstance(links, dict):
            continue
        arr = links.get("Ports")
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            oid = item.get("@odata.id")
            if isinstance(oid, str) and "/Ports/" in oid and oid.strip():
                return oid.strip()
    return None


def effective_lenovo_ports(ctx: NormalizationContext) -> Any:
    """``Ports`` collection link. Synthesized from ``Controllers[].Links.Ports`` when the BMC omits it.

    Some XCC builds omit the top-level ``Ports`` link but still list
    ``Controllers[].Links.Ports``. Expose the canonical ``Ports`` collection URL there;
    the Lenovo Ports rule fills that collection from the PCIe functions.
    """
    raw = ctx.data.get("Ports")
    if isinstance(raw, dict):
        oid = raw.get("@odata.id")
        if isinstance(oid, str) and oid.strip():
            return raw
    if isinstance(ctx.data, dict) and _first_controller_ports_member_uri(ctx.data):
        base = ctx.odata_id.rstrip("/")
        return {"@odata.id": f"{base}/Ports"}
    return raw if isinstance(raw, dict) else {}


def _lenovo_network_adapter_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    """Promote Oem.Lenovo.UUID into Oem.Redpool.UUID for collector uuid labels."""
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    rp: Dict[str, Any] = (
        dict(out.get("Redpool") or {}) if isinstance(out.get("Redpool"), dict) else {}
    )
    lnv = out.get("Lenovo")
    if isinstance(lnv, dict):
        uuid = lnv.get("UUID")
        if isinstance(uuid, str) and uuid.strip():
            rp["UUID"] = uuid.strip()
    if rp:
        out["Redpool"] = rp
    return out


class LenovoChassisNetworkAdapterNormalizer(BaseNetworkAdapterNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_lenovo_network_adapter_pcie(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Status"] = effective_lenovo_network_adapter_status
        m["Ports"] = effective_lenovo_ports
        m["Oem"] = _lenovo_network_adapter_oem
        return m
