# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell chassis PCIe inventory: one walk per context, pure matchers over it.

:func:`load_chassis_pcie_inventory` walks ``{chassis}/PCIeDevices`` → each device →
its ``PCIeFunctions`` collection → each function once and stores the result in
``ctx.prefetched``. The ``match_*`` functions then pick a device / function for a
NetworkAdapter, NetworkPort or EthernetInterface without further requests.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from redpool.redfish_client import redfish_get_json

from ..types import NormalizationContext

PcieInventory = List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]

_INVENTORY_KEY = "_dell_chassis_pcie_inventory"

_SLOT_ADAPTER_ID = re.compile(r"^NIC\.Slot\.(\d+)$", re.IGNORECASE)


def _member_ids(coll: Any) -> List[str]:
    members = coll.get("Members") if isinstance(coll, dict) else None
    if not isinstance(members, list):
        return []
    out: List[str] = []
    for ref in members:
        if not isinstance(ref, dict):
            continue
        oid = ref.get("@odata.id")
        if isinstance(oid, str):
            out.append(oid)
    return out


def _walk_device_functions(client: Any, pcie: Dict[str, Any]) -> List[Dict[str, Any]]:
    link = pcie.get("PCIeFunctions")
    if not isinstance(link, dict):
        return []
    coll_id = link.get("@odata.id")
    if not isinstance(coll_id, str):
        return []
    functions: List[Dict[str, Any]] = []
    for m_id in _member_ids(redfish_get_json(client, coll_id)):
        fn = redfish_get_json(client, m_id)
        if fn:
            functions.append(fn)
    return functions


def load_chassis_pcie_inventory(
    ctx: NormalizationContext, chassis_path: str
) -> PcieInventory:
    """Walk the chassis PCIe tree once per *ctx* and *chassis_path*; later calls reuse it."""
    cache = ctx.prefetched.setdefault(_INVENTORY_KEY, {})
    cached = cache.get(chassis_path)
    if cached is not None:
        return cached
    inventory: PcieInventory = []
    for oid in _member_ids(redfish_get_json(ctx.client, f"{chassis_path}/PCIeDevices")):
        pcie = redfish_get_json(ctx.client, oid)
        if not pcie:
            continue
        inventory.append((pcie, _walk_device_functions(ctx.client, pcie)))
    cache[chassis_path] = inventory
    return inventory


def slot_ordinal_from_network_adapter_id(adapter_id: str) -> Optional[int]:
    if not isinstance(adapter_id, str):
        return None
    m = _SLOT_ADAPTER_ID.match(adapter_id.strip())
    if not m:
        return None
    return int(m.group(1), 10)


def dell_oem_pcie_function_id(fn: Dict[str, Any]) -> Optional[str]:
    """Dell ``Oem.Dell.DellPCIeFunction.Id`` (NIC id for this function / port)."""
    oem = fn.get("Oem")
    if not isinstance(oem, dict):
        return None
    dell = oem.get("Dell")
    if not isinstance(dell, dict):
        return None
    inner = dell.get("DellPCIeFunction")
    if isinstance(inner, dict):
        nid = inner.get("Id")
        if isinstance(nid, str) and nid.strip():
            return nid.strip()
    return None


def _eth_interface_tail(odata_id: str) -> Optional[str]:
    if "/EthernetInterfaces/" not in odata_id:
        return None
    return odata_id.rsplit("/", 1)[-1]


def _function_links_nic_id(fn: Dict[str, Any], nic_id: str) -> bool:
    prefix = nic_id + "-"
    did = dell_oem_pcie_function_id(fn)
    if isinstance(did, str):
        if did == nic_id or did.startswith(prefix):
            return True
    links = fn.get("Links")
    if not isinstance(links, dict):
        return False
    arr = links.get("EthernetInterfaces")
    if not isinstance(arr, list):
        return False
    for item in arr:
        if not isinstance(item, dict):
            continue
        oid = item.get("@odata.id")
        if not isinstance(oid, str):
            continue
        tail = _eth_interface_tail(oid)
        if tail and (tail == nic_id or tail.startswith(prefix)):
            return True
    return False


def pcie_function_links_network_adapter(fn: Dict[str, Any], adapter_id: str) -> bool:
    """True if this PCIeFunction belongs to the given NetworkAdapter ``Id``."""
    return _function_links_nic_id(fn, adapter_id)


def pcie_function_links_network_port(fn: Dict[str, Any], port_id: str) -> bool:
    """True if this PCIeFunction maps to chassis ``NetworkPort`` ``Id`` (e.g. ``NIC.Integrated.1-1``).

    Matches Dell ``DellPCIeFunction.Id`` (e.g. ``NIC.Integrated.1-1-1``) or
    ``Links.EthernetInterfaces`` tails that share the port id prefix (partition
    suffix on the host interface).
    """
    return _function_links_nic_id(fn, port_id)


def _function_links_ethernet_interface(fn: Dict[str, Any], eth_odata_id: str) -> bool:
    links = fn.get("Links")
    if not isinstance(links, dict):
        return False
    arr = links.get("EthernetInterfaces")
    if not isinstance(arr, list):
        return False
    for item in arr:
        if not isinstance(item, dict):
            continue
        eid = item.get("@odata.id")
        if isinstance(eid, str) and eid == eth_odata_id:
            return True
    return False


def _coerce_status_subset(st: Any) -> Dict[str, Any]:
    if not isinstance(st, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in ("Health", "State", "HealthRollup"):
        if k in st and st[k] is not None:
            out[k] = st[k]
    return out


def _pci_slot_ordinal(pcie: Dict[str, Any]) -> Optional[int]:
    slot = pcie.get("Slot")
    if not isinstance(slot, dict):
        return None
    loc = slot.get("Location")
    if not isinstance(loc, dict):
        return None
    pl = loc.get("PartLocation")
    if not isinstance(pl, dict):
        return None
    v = pl.get("LocationOrdinalValue")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip(), 10)
    return None


def _first_match(
    inventory: PcieInventory, predicate: Any
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    for pcie, functions in inventory:
        for fn in functions:
            if predicate(fn):
                return pcie, fn
    return None


def _status_fn_then_device(
    pcie: Dict[str, Any], fn: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    st_fn = _coerce_status_subset(fn.get("Status"))
    if st_fn:
        return st_fn
    st_dev = _coerce_status_subset(pcie.get("Status"))
    return st_dev if st_dev else None


def match_port_display(
    inventory: PcieInventory, port_id: str
) -> Optional[Dict[str, str]]:
    """``Name`` / ``Description`` from the PCIeFunction (or device) for *port_id*."""
    hit = _first_match(
        inventory, lambda fn: pcie_function_links_network_port(fn, port_id)
    )
    if hit is None:
        return None
    pcie, fn = hit
    out: Dict[str, str] = {}
    n = fn.get("Name")
    if isinstance(n, str) and n.strip():
        out["Name"] = n.strip()
    d = fn.get("Description")
    if isinstance(d, str) and d.strip():
        out["Description"] = d.strip()
    if not out.get("Name"):
        pn = pcie.get("Name")
        if isinstance(pn, str) and pn.strip():
            out["Name"] = pn.strip()
    if not out.get("Description"):
        pd = pcie.get("Description")
        if isinstance(pd, str) and pd.strip():
            out["Description"] = pd.strip()
    return out if out else None


def match_port_status(
    inventory: PcieInventory, port_id: str
) -> Optional[Dict[str, Any]]:
    """``Status`` subset from the PCIe function (else device) for *port_id*."""
    hit = _first_match(
        inventory, lambda fn: pcie_function_links_network_port(fn, port_id)
    )
    if hit is None:
        return None
    return _status_fn_then_device(*hit)


def match_ethernet_status(
    inventory: PcieInventory, eth_odata_id: str
) -> Optional[Dict[str, Any]]:
    """``Status`` subset from the PCIe function (else device) linked to *eth_odata_id*."""
    hit = _first_match(
        inventory, lambda fn: _function_links_ethernet_interface(fn, eth_odata_id)
    )
    if hit is None:
        return None
    return _status_fn_then_device(*hit)


def _first_function_summary(
    functions: List[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[str]]:
    if not functions:
        return None, None
    fn = functions[0]
    dc = fn.get("DeviceClass")
    desc = fn.get("Description")
    return (
        dc if isinstance(dc, str) else None,
        desc if isinstance(desc, str) else None,
    )


def _is_likely_network_pcie(
    pcie: Dict[str, Any], functions: List[Dict[str, Any]]
) -> bool:
    name = pcie.get("Name")
    desc = pcie.get("Description")
    name_s = name.strip() if isinstance(name, str) else ""
    desc_s = desc.strip() if isinstance(desc, str) else ""
    blob = f"{desc_s} {name_s}".lower()
    if (
        "network" in blob
        or "ethernet" in blob
        or "mellanox" in blob
        or "connectx" in blob
    ):
        return True
    dc, _ = _first_function_summary(functions)
    return bool(dc and "network" in dc.lower())


def _slot_candidates(inventory: PcieInventory, adapter_id: str) -> PcieInventory:
    want_slot = slot_ordinal_from_network_adapter_id(adapter_id)
    if want_slot is None:
        return []
    return [
        (pcie, functions)
        for pcie, functions in inventory
        if _pci_slot_ordinal(pcie) == want_slot
        and _is_likely_network_pcie(pcie, functions)
    ]


def _device_matching_adapter_functions(
    inventory: PcieInventory, adapter_id: str
) -> Optional[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    for pcie, functions in inventory:
        if any(pcie_function_links_network_adapter(fn, adapter_id) for fn in functions):
            return pcie, functions
    return None


def match_adapter(
    inventory: PcieInventory, adapter_id: str
) -> Optional[Dict[str, Any]]:
    """PCIeDevice for *adapter_id*: by function links, else by Dell slot ordinal."""
    by_functions = _device_matching_adapter_functions(inventory, adapter_id)
    if by_functions:
        return by_functions[0]
    candidates = _slot_candidates(inventory, adapter_id)
    return candidates[0][0] if candidates else None


def _adapter_status_on_device(
    pcie: Dict[str, Any], functions: List[Dict[str, Any]], adapter_id: str
) -> Optional[Dict[str, Any]]:
    st_dev = _coerce_status_subset(pcie.get("Status"))
    if st_dev:
        return st_dev
    for fn in functions:
        if pcie_function_links_network_adapter(fn, adapter_id):
            st_fn = _coerce_status_subset(fn.get("Status"))
            if st_fn:
                return st_fn
    return None


def match_adapter_status(
    inventory: PcieInventory, adapter_id: str
) -> Optional[Dict[str, Any]]:
    """``Status`` subset from the PCIe device (or its functions) for *adapter_id*."""
    by_functions = _device_matching_adapter_functions(inventory, adapter_id)
    if by_functions:
        st = _adapter_status_on_device(*by_functions, adapter_id)
        if st:
            return st
    for pcie, functions in _slot_candidates(inventory, adapter_id):
        st = _adapter_status_on_device(pcie, functions, adapter_id)
        if st:
            return st
    return None
