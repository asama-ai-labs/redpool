# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell Chassis NetworkAdapter: PCIe-based inventory and display enrichment.

Match ``PCIeDevice`` → ``PCIeFunctions`` to a NetworkAdapter using:

- Dell OEM ``Oem.Dell.DellPCIeFunction.Id`` (e.g. ``NIC.Slot.3-1`` under adapter
  ``NIC.Slot.3``, or ``NIC.Integrated.1-2-1`` under ``NIC.Integrated.1``), or
- ``Links.EthernetInterfaces[].@odata.id`` tail after ``.../EthernetInterfaces/``.

Fallback (Dell slot NICs): ``NIC.Slot.{n}`` + PCIe ``Slot.Location...LocationOrdinalValue == n``
with heuristics when OEM / Ethernet links are absent.

The chassis PCIe tree is walked once per context by ``_shared.dell_pcie_inventory``;
``match_adapter_status`` copies ``Status`` (``Health`` / ``State`` / ``HealthRollup``)
from the matching PCIeFunction or PCIeDevice when the resource omits them or reports
``Unknown``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from ..._shared.status_fields import (
    adapter_status_needs_pcie_fill,
    status_field_unknown_or_empty,
)
from ..._shared.dell_assembly_fru import (
    dell_chassis_path_from_resource_odata_id,
    fetch_chassis_assembly_redpool_fields,
    merge_redpool_assembly_fields,
)
from ..._shared.dell_nic_product import nic_fields
from ..._shared.dell_pcie_inventory import (
    load_chassis_pcie_inventory,
    match_adapter,
    match_adapter_status,
)
from ...types import NormalizationContext
from .base import BaseNetworkAdapterNormalizer

_DELL_NA_ASSEMBLY_FRU = "DellNetworkAdapterAssemblyFru"

_PREFETCH_KEY = "_network_adapter_pcie_enrichment"
_PREFETCH_STATUS_KEY = "_dell_network_adapter_pcie_status"
_PRODUCT_NAME_KEY = "_dell_network_adapter_product_name"
_NIC_VENDOR_KEY = "_dell_network_adapter_nic_vendor"

_GENERIC_ADAPTER_NAMES = frozenset(
    s.lower() for s in ("Network Adapter View", "Network Adapter", "Adapter View")
)


def _is_generic_adapter_name(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or not value.strip():
        return True
    return value.strip().lower() in _GENERIC_ADAPTER_NAMES


def chassis_path_from_network_adapter_odata_id(odata_id: str) -> Optional[str]:
    if not isinstance(odata_id, str) or "/NetworkAdapters/" not in odata_id:
        return None
    return odata_id.split("/NetworkAdapters/", 1)[0]


def _store_prefetch_from_pcie(
    ctx: NormalizationContext,
    data: Dict[str, Any],
    pcie: Dict[str, Any],
    *,
    fill_model: bool = True,
) -> None:
    name = pcie.get("Name")
    desc = pcie.get("Description")
    name_s = name.strip() if isinstance(name, str) else ""
    desc_s = desc.strip() if isinstance(desc, str) else ""
    adapter_mfg = data.get("Manufacturer")
    out: Dict[str, Any] = {}
    if fill_model:
        if name_s:
            out["Model"] = name_s
        elif desc_s:
            out["Model"] = desc_s
    pcie_mfg = pcie.get("Manufacturer")
    if not (isinstance(adapter_mfg, str) and adapter_mfg.strip()):
        if isinstance(pcie_mfg, str) and pcie_mfg.strip():
            out["Manufacturer"] = pcie_mfg.strip()
    if _is_generic_adapter_name(data.get("Name")):
        src = name_s or desc_s
        if src:
            out["Name"] = src
    fw = pcie.get("FirmwareVersion")
    if isinstance(fw, str) and fw.strip():
        out["FirmwareVersion"] = fw.strip()
    if out:
        ctx.prefetched[_PREFETCH_KEY] = out


def prefetch_network_adapter_pcie(ctx: NormalizationContext) -> None:
    ctx.prefetched.pop(_PREFETCH_KEY, None)
    if ctx.client is None:
        return
    data = ctx.data
    adapter_id = data.get("Id")
    if not isinstance(adapter_id, str):
        return
    model_missing = data.get("Model") is None or not str(data.get("Model")).strip()
    need_display = _is_generic_adapter_name(data.get("Name"))
    if not model_missing and not need_display:
        return
    chassis_path = chassis_path_from_network_adapter_odata_id(ctx.odata_id)
    if not chassis_path:
        return

    pcie = match_adapter(load_chassis_pcie_inventory(ctx, chassis_path), adapter_id)
    if pcie:
        _store_prefetch_from_pcie(ctx, data, pcie, fill_model=model_missing)


def prefetch_network_adapter_pcie_status(ctx: NormalizationContext) -> None:
    """Prefetch PCIe ``Status`` when adapter ``Status`` is incomplete or ``Unknown``."""
    ctx.prefetched.pop(_PREFETCH_STATUS_KEY, None)
    if ctx.client is None:
        return
    if not adapter_status_needs_pcie_fill(ctx.data.get("Status")):
        return
    adapter_id = ctx.data.get("Id")
    if not isinstance(adapter_id, str):
        return
    chassis_path = chassis_path_from_network_adapter_odata_id(ctx.odata_id)
    if not chassis_path:
        return
    st = match_adapter_status(
        load_chassis_pcie_inventory(ctx, chassis_path), adapter_id
    )
    if st:
        ctx.prefetched[_PREFETCH_STATUS_KEY] = st


def _pcie_adapter_status_overlay(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_PREFETCH_STATUS_KEY)
    return raw if isinstance(raw, dict) else {}


def effective_network_adapter_status(ctx: NormalizationContext) -> Any:
    """Merge chassis PCIe ``Status`` when adapter ``Status`` is missing or ``Unknown``."""
    raw = ctx.data.get("Status")
    base: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    overlay = _pcie_adapter_status_overlay(ctx)
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


def _enrich(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_PREFETCH_KEY)
    return raw if isinstance(raw, dict) else {}


def _adapter_product_name(ctx: NormalizationContext) -> Optional[str]:
    raw = ctx.prefetched.get(_PRODUCT_NAME_KEY)
    return raw if isinstance(raw, str) and raw else None


def prefetch_dell_adapter_product_name(ctx: NormalizationContext) -> None:
    """Read ``DellNIC`` product and vendor names from the functions when nothing else gives them.

    Run after the PCIe prefetch. An adapter with no PCIe function (an embedded LOM) has
    neither a model, a real name nor a manufacturer, but its NetworkDeviceFunctions carry them.
    """
    ctx.prefetched.pop(_PRODUCT_NAME_KEY, None)
    ctx.prefetched.pop(_NIC_VENDOR_KEY, None)
    if ctx.client is None:
        return
    wanted = []
    if (
        _is_generic_adapter_name(effective_adapter_name(ctx))
        or not str(effective_adapter_model(ctx) or "").strip()
    ):
        wanted.append("ProductName")
    if not str(effective_adapter_manufacturer(ctx) or "").strip():
        wanted.append("VendorName")
    if not wanted:
        return
    paths = [
        link["@odata.id"]
        for controller in ctx.data.get("Controllers") or []
        if isinstance(controller, dict)
        for link in (controller.get("Links") or {}).get("NetworkDeviceFunctions") or []
        if isinstance(link, dict) and isinstance(link.get("@odata.id"), str)
    ]
    found = nic_fields(ctx.client, paths, wanted)
    if "ProductName" in found:
        ctx.prefetched[_PRODUCT_NAME_KEY] = found["ProductName"]
    if "VendorName" in found:
        ctx.prefetched[_NIC_VENDOR_KEY] = found["VendorName"]


def effective_adapter_model(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Model")
    if raw is not None and str(raw).strip():
        return raw
    v = _enrich(ctx).get("Model")
    return v or _adapter_product_name(ctx) or raw


def effective_adapter_name(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Name")
    if isinstance(raw, str) and raw.strip() and not _is_generic_adapter_name(raw):
        return raw
    if raw is not None and not isinstance(raw, str):
        return raw
    v = _enrich(ctx).get("Name")
    return v or _adapter_product_name(ctx) or raw


def effective_adapter_manufacturer(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Manufacturer")
    if raw is not None and str(raw).strip():
        return raw
    v = _enrich(ctx).get("Manufacturer")
    if v:
        return v
    return ctx.prefetched.get(_NIC_VENDOR_KEY) or raw


def effective_adapter_controllers(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Controllers")
    if not isinstance(raw, list):
        raw = []
    fw = _enrich(ctx).get("FirmwareVersion")
    if not isinstance(fw, str) or not fw.strip():
        return raw
    out: List[Any] = copy.deepcopy(raw) if raw else []
    if not out:
        return [{"FirmwarePackageVersion": fw}]
    first = out[0]
    if isinstance(first, dict):
        existing = first.get("FirmwarePackageVersion")
        if existing is None or (isinstance(existing, str) and not existing.strip()):
            merged = dict(first)
            merged["FirmwarePackageVersion"] = fw
            out[0] = merged
    return out


def prefetch_dell_network_adapter_assembly_fru(ctx: NormalizationContext) -> None:
    if ctx.client is None:
        return
    adapter_id = ctx.data.get("Id")
    if not isinstance(adapter_id, str) or not adapter_id.strip():
        return
    chassis_path = dell_chassis_path_from_resource_odata_id(ctx.odata_id or "")
    if not chassis_path:
        return
    fields = fetch_chassis_assembly_redpool_fields(
        ctx.client, chassis_path, adapter_id.strip()
    )
    if not fields:
        return
    if ctx.prefetched is None:
        ctx.prefetched = {}
    ctx.prefetched[_DELL_NA_ASSEMBLY_FRU] = fields


def _dell_network_adapter_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    rp: Dict[str, Any] = (
        dict(out.get("Redpool") or {}) if isinstance(out.get("Redpool"), dict) else {}
    )
    mfg = (ctx.prefetched or {}).get(_DELL_NA_ASSEMBLY_FRU)
    if isinstance(mfg, dict):
        merge_redpool_assembly_fields(rp, mfg)
    if rp:
        out["Redpool"] = rp
    else:
        out.pop("Redpool", None)
    return out


class DellChassisNetworkAdapterNormalizer(BaseNetworkAdapterNormalizer):
    """Dell: prefetch PCIe inventory and merge into NetworkAdapter fields."""

    def prefetch(self, ctx: NormalizationContext) -> None:
        ctx.prefetched.pop(_PREFETCH_KEY, None)
        ctx.prefetched.pop(_PREFETCH_STATUS_KEY, None)
        ctx.prefetched.pop(_PRODUCT_NAME_KEY, None)
        prefetch_network_adapter_pcie(ctx)
        prefetch_network_adapter_pcie_status(ctx)
        prefetch_dell_adapter_product_name(ctx)
        prefetch_dell_network_adapter_assembly_fru(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Status"] = effective_network_adapter_status
        m["Name"] = effective_adapter_name
        m["Manufacturer"] = effective_adapter_manufacturer
        m["Model"] = effective_adapter_model
        m["Controllers"] = effective_adapter_controllers
        m["Oem"] = _dell_network_adapter_oem
        return m
