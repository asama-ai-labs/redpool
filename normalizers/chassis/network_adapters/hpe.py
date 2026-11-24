# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE Chassis NetworkAdapter: PCIe ``Status`` enrichment and ``Ports`` → ``NetworkPorts``.

HPE often omits ``Status.HealthRollup`` while ``Controllers[].Links.PCIeDevices``
points at a chassis ``PCIeDevice`` with concrete ``Health`` / ``State``. Some OCP
adapters omit ``Controllers[].Links.PCIeDevices``; we match a ``PCIeDevice`` by
identity (``Id``) or by strong name / part / firmware hints and merge ``Status``.

When rollup is still unknown but ``Health`` is a known value, set
``HealthRollup`` to ``Health``.

When ``NetworkPorts`` is missing but ``Ports`` exposes ``@odata.id``, emit the
canonical ``NetworkPorts`` collection link (see ``redfish-inventory-exporter`` /
gofish).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from redpool.redfish_client import redfish_get_json

from ...optional import OMIT
from ...types import NormalizationContext
from .base import BaseNetworkAdapterNormalizer
from normalizers._shared.status_fields import (
    adapter_status_needs_pcie_fill,
    status_field_unknown_or_empty,
)
from .lenovo import (
    effective_lenovo_ports,
    lenovo_network_adapter_pcie_device_uris,
)

_HPE_ADAPTER_PCIE_STATUS_KEY = "_hpe_network_adapter_pcie_status"


def _coerce_status_subset(st: Any) -> Dict[str, Any]:
    if not isinstance(st, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in ("Health", "State", "HealthRollup"):
        if k in st and st[k] is not None:
            out[k] = st[k]
    return out


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


def _chassis_prefix_from_adapter_odata_id(odata_id: str) -> Optional[str]:
    if not isinstance(odata_id, str) or "/NetworkAdapters/" not in odata_id:
        return None
    return odata_id.split("/NetworkAdapters/", 1)[0]


def _norm_ident(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return " ".join(value.strip().lower().split())


def _controller_firmware(adapter: Dict[str, Any]) -> str:
    controllers = adapter.get("Controllers")
    if not isinstance(controllers, list):
        return ""
    for ctl in controllers:
        if not isinstance(ctl, dict):
            continue
        ver = ctl.get("FirmwarePackageVersion")
        if isinstance(ver, str) and ver.strip():
            return ver.strip()
    return ""


def _pcie_status_nonempty(st: Dict[str, Any]) -> bool:
    for k in ("Health", "State", "HealthRollup"):
        v = st.get(k)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, str) and v.strip().casefold() == "unknown":
            continue
        return True
    return False


def _score_pcie_device_match(dev: Dict[str, Any], adapter: Dict[str, Any]) -> int:
    aid = adapter.get("Id")
    if isinstance(aid, str) and aid and aid == dev.get("Id"):
        return 100
    amodel = _norm_ident(adapter.get("Model"))
    aname = _norm_ident(adapter.get("Name"))
    dname = _norm_ident(dev.get("Name"))
    dmodel = _norm_ident(dev.get("Model"))
    for a in (amodel, aname):
        if not a:
            continue
        for d in (dname, dmodel):
            if not d:
                continue
            if a == d:
                return 90
            if a in d or d in a:
                return 80
    apn = adapter.get("PartNumber")
    dpn = dev.get("PartNumber")
    if isinstance(apn, str) and isinstance(dpn, str) and apn.strip() and apn == dpn:
        return 70
    cfw = _controller_firmware(adapter)
    dfw = dev.get("FirmwareVersion")
    if isinstance(cfw, str) and isinstance(dfw, str) and cfw and cfw == dfw.strip():
        return 60
    return 0


def _iter_pcie_member_uris(client: Any, chassis_prefix: str) -> List[str]:
    coll = redfish_get_json(client, f"{chassis_prefix.rstrip('/')}/PCIeDevices")
    members = coll.get("Members") if isinstance(coll, dict) else None
    if not isinstance(members, list):
        return []
    out: List[str] = []
    for ref in members:
        if not isinstance(ref, dict):
            continue
        oid = ref.get("@odata.id")
        if isinstance(oid, str) and oid.strip():
            out.append(oid.strip())
    return out


def resolve_hpe_adapter_pcie_status_overlay(
    client: Any,
    adapter: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a ``Status``-like dict to merge when the adapter omits rollup or health/state."""
    for uri in lenovo_network_adapter_pcie_device_uris(adapter):
        st = _status_from_pcie_resource(client, uri)
        if st and _pcie_status_nonempty(st):
            return st

    chassis = _chassis_prefix_from_adapter_odata_id(
        adapter.get("@odata.id", "") if isinstance(adapter, dict) else ""
    )
    if not chassis or not client:
        return {}

    best: Dict[str, Any] = {}
    best_score = 0
    for m_uri in _iter_pcie_member_uris(client, chassis):
        dev = redfish_get_json(client, m_uri)
        if not isinstance(dev, dict):
            continue
        score = _score_pcie_device_match(dev, adapter)
        if score < 50:
            continue
        st = _status_from_pcie_resource(client, m_uri)
        if not st or not _pcie_status_nonempty(st):
            continue
        if score > best_score:
            best_score = score
            best = st
    return best


def prefetch_hpe_network_adapter_pcie(ctx: NormalizationContext) -> None:
    ctx.prefetched.pop(_HPE_ADAPTER_PCIE_STATUS_KEY, None)
    if ctx.client is None:
        return
    if not adapter_status_needs_pcie_fill(ctx.data.get("Status")):
        return
    st = resolve_hpe_adapter_pcie_status_overlay(ctx.client, ctx.data)
    if st:
        ctx.prefetched[_HPE_ADAPTER_PCIE_STATUS_KEY] = st


def _infer_health_rollup_from_health(out: Dict[str, Any]) -> None:
    if not status_field_unknown_or_empty(out.get("HealthRollup")):
        return
    h = out.get("Health")
    if isinstance(h, str):
        t = h.strip()
        if t and t.casefold() != "unknown":
            out["HealthRollup"] = t


def _hpe_pcie_status_overlay(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_HPE_ADAPTER_PCIE_STATUS_KEY)
    return raw if isinstance(raw, dict) else {}


def effective_hpe_network_adapter_status(ctx: NormalizationContext) -> Any:
    """Merge PCIe ``Status``; infer ``HealthRollup`` from ``Health`` when still unknown."""
    raw = ctx.data.get("Status")
    base: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    overlay = _hpe_pcie_status_overlay(ctx)
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


def _is_hpe_base_adapter_shape(ctx: NormalizationContext) -> bool:
    if isinstance(ctx.data.get("PhysicalPorts"), list):
        return True
    odt = ctx.data.get("@odata.type")
    return isinstance(odt, str) and "HpeBaseNetworkAdapter" in odt


def effective_hpe_ports(ctx: NormalizationContext) -> Any:
    """Prefer a ``Ports`` link to the adapter's ``PhysicalPorts`` (BaseNetworkAdapter)."""
    if _is_hpe_base_adapter_shape(ctx):
        pp = ctx.data.get("PhysicalPorts")
        if isinstance(pp, list) and pp:
            base = ctx.odata_id.rstrip("/")
            return {"@odata.id": f"{base}/Ports"}
    return effective_lenovo_ports(ctx)


def effective_hpe_network_adapter_manufacturer(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Manufacturer")
    if isinstance(raw, str) and raw.strip():
        return raw
    if _is_hpe_base_adapter_shape(ctx):
        return "Hewlett Packard Enterprise"
    return raw


def effective_hpe_network_adapter_model(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Model")
    if isinstance(raw, str) and raw.strip():
        return raw
    if _is_hpe_base_adapter_shape(ctx):
        name = ctx.data.get("Name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return raw


def effective_hpe_network_adapter_part_number(ctx: NormalizationContext) -> Any:
    """Prefer BMC PartNumber; if missing/blank/N/F, use Oem.Hpe.PCAVersion."""
    raw = ctx.data.get("PartNumber")
    if isinstance(raw, str):
        s = raw.strip()
        if s and s.upper() != "N/F":
            return raw  # preserve original spacing when usable
    elif raw is not None:
        return raw  # non-string PartNumber: do not invent a string

    oem = ctx.data.get("Oem")
    if not isinstance(oem, dict):
        return raw
    hpe = oem.get("Hpe") or oem.get("HPE")
    if not isinstance(hpe, dict):
        return raw
    pca = hpe.get("PCAVersion")
    if isinstance(pca, str):
        p = pca.strip()
        if p and p.upper() != "N/F":
            return p
    return raw


_BASE_ADAPTER_OEM_KEYS = (
    "PhysicalPorts",
    "StructuredName",
    "UEFIDevicePath",
    "FcPorts",
    "Firmware",
    "Location",
)


def effective_hpe_network_adapter_oem(ctx: NormalizationContext) -> Any:
    """Keep BaseNetworkAdapter fields that NetworkAdapter does not define."""
    raw = ctx.data.get("Oem")
    oem = dict(raw) if isinstance(raw, dict) else {}
    if not _is_hpe_base_adapter_shape(ctx):
        return oem
    kept = {key: ctx.data[key] for key in _BASE_ADAPTER_OEM_KEYS if key in ctx.data}
    if not kept:
        return oem
    existing = oem.get("Redpool")
    redpool = dict(existing) if isinstance(existing, dict) else {}
    redpool.update(kept)
    oem["Redpool"] = redpool
    return oem


def _hpe_adapter_link(key: str):
    """Omit empty link objects on a BaseNetworkAdapter. Other HPE adapters keep the base default."""

    def _read(ctx: NormalizationContext) -> Any:
        if not _is_hpe_base_adapter_shape(ctx):
            return ctx.data.get(key, {})
        value = ctx.data.get(key)
        if isinstance(value, dict) and value:
            return value
        if isinstance(value, list) and value:
            return value
        return OMIT

    return _read


def effective_hpe_network_adapter_controllers(ctx: NormalizationContext) -> Any:
    existing = ctx.data.get("Controllers")
    if isinstance(existing, list) and existing:
        return existing
    if not _is_hpe_base_adapter_shape(ctx):
        return []
    fw = ctx.data.get("Firmware")
    ver = ""
    if isinstance(fw, dict):
        cur = fw.get("Current")
        if isinstance(cur, dict):
            vs = cur.get("VersionString")
            if isinstance(vs, str) and vs.strip():
                ver = vs.strip()
    if not ver:
        return []
    return [{"FirmwarePackageVersion": ver}]


class HPEChassisNetworkAdapterNormalizer(BaseNetworkAdapterNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_hpe_network_adapter_pcie(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Status"] = effective_hpe_network_adapter_status
        m["Ports"] = effective_hpe_ports
        m["Manufacturer"] = effective_hpe_network_adapter_manufacturer
        m["Model"] = effective_hpe_network_adapter_model
        m["PartNumber"] = effective_hpe_network_adapter_part_number
        m["Controllers"] = effective_hpe_network_adapter_controllers
        m["Oem"] = effective_hpe_network_adapter_oem
        for key in ("NetworkDeviceFunctions", "Assembly", "Actions"):
            m[key] = _hpe_adapter_link(key)
        return m
