# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo: serve ``.../NetworkAdapters/{id}/Ports`` (DMTF ``#Port``) on every XCC.

ThinkSystem XCC may leave ``Ports`` collections empty, or omit them, while the adapter
still links PCIe functions. ``redfish-inventory-exporter`` reads ``Ports`` only, so this
rule fills those collections from the PCIe functions. ``NetworkPorts`` is not rewritten.

When ``Ports`` / ``NetworkPorts`` collections return empty ``Members`` but the adapter
links a ``PCIeDevice`` with ``PCIeFunctions``, we synthesize port member URLs and, on
404 for ``.../Ports/{n}``, return a minimal ``#Port`` built from the matching function.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from redpool.redfish_client import redfish_get_json

from ...apply import normalize_resource
from ...request_rewrites import (
    RequestRewriteRule,
    RewriteCall,
    register_request_rewrite,
)
from ...types import NormalizationContext
from ..ports.lenovo import LenovoChassisPortNormalizer
from .base import prepare_port_document

_registration_state = {"done": False}
_LOG = logging.getLogger(__name__)

_NETWORK_PORT_NAMES = (
    "ActiveLinkTechnology",
    "AssociatedNetworkAddresses",
    "CurrentLinkSpeedMbps",
    "PhysicalPortNumber",
)

_MAX_SYNTH_PORTS = 64


def _adapter_base_from_ports_related_path(path: str) -> Optional[str]:
    """Return ``.../NetworkAdapters/{id}`` given a ``Ports`` URL."""
    p = path.rstrip("/")
    parts = p.split("/")
    if len(parts) < 2:
        return None
    if parts[-1].isdigit() and parts[-2] == "Ports":
        return "/".join(parts[:-2])
    if parts[-1] == "Ports":
        return "/".join(parts[:-1])
    return None


def _primary_pcie_device_uri(adapter: dict) -> Optional[str]:
    controllers = adapter.get("Controllers")
    if not isinstance(controllers, list):
        return None
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
                return oid.strip()
    return None


def _pci_function_uris_from_pcie_device(pcie: dict) -> List[str]:
    links = pcie.get("Links")
    if not isinstance(links, dict):
        return []
    arr = links.get("PCIeFunctions")
    if not isinstance(arr, list):
        return []
    out: List[str] = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        oid = item.get("@odata.id")
        if isinstance(oid, str) and oid.strip():
            out.append(oid.strip())
    return out


def _is_network_pcie_function(fn: dict) -> bool:
    if fn.get("DeviceClass") == "NetworkController":
        return True
    cc = fn.get("ClassCode")
    if isinstance(cc, str) and cc.lower().startswith("0x02"):
        return True
    return False


def _lenovo_sorted_network_pcie_function_uris(
    client: Any,
    pcie_uri: str,
) -> List[str]:
    pcie = redfish_get_json(client, pcie_uri)
    if not isinstance(pcie, dict):
        return []
    uris = _pci_function_uris_from_pcie_device(pcie)
    if not uris:
        return []
    scored: List[Tuple[int, str, str]] = []
    for uri in uris:
        fn = redfish_get_json(client, uri)
        if not isinstance(fn, dict):
            continue
        if not _is_network_pcie_function(fn):
            continue
        fid = fn.get("FunctionId")
        try:
            fkey = int(fid) if fid is not None else 10**9
        except (TypeError, ValueError):
            fkey = 10**9
        sid = str(fn.get("Id") or uri)
        scored.append((fkey, sid, uri))
    if not scored:
        for uri in uris:
            fn = redfish_get_json(client, uri)
            if isinstance(fn, dict) and _is_network_pcie_function(fn):
                scored.append((10**9, uri, uri))
    if not scored:
        scored = [(10**9, u, u) for u in uris]
    scored.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in scored]


def _lenovo_fill_empty_port_collection(
    client: Any,
    backend_path: str,
    body: dict,
) -> Optional[dict]:
    if client is None:
        return None
    coll = backend_path.rstrip("/")
    if not coll.endswith("/Ports"):
        return None
    members = body.get("Members")
    if isinstance(members, list) and members:
        return None
    adapter_base = _adapter_base_from_ports_related_path(coll)
    if not adapter_base:
        return None
    adapter = redfish_get_json(client, adapter_base)
    if not isinstance(adapter, dict):
        return None
    pcie_uri = _primary_pcie_device_uri(adapter)
    if not pcie_uri:
        return None
    fn_uris = _lenovo_sorted_network_pcie_function_uris(client, pcie_uri)
    if not fn_uris:
        return None
    n = min(len(fn_uris), _MAX_SYNTH_PORTS)
    new_members = [{"@odata.id": f"{coll}/{i + 1}"} for i in range(n)]
    merged = dict(body)
    merged["Members"] = new_members
    merged["Members@odata.count"] = n
    return merged


def _lenovo_port_index_from_paths(path: str, backend_path: str) -> Optional[int]:
    for p in (backend_path.rstrip("/"), path.rstrip("/")):
        parts = p.split("/")
        if len(parts) >= 2 and parts[-2] == "Ports" and parts[-1].isdigit():
            return int(parts[-1], 10)
    m = re.search(r"/(?:Network)?Ports/(\d+)\Z", path.rstrip("/"), re.I)
    if m:
        return int(m.group(1), 10)
    return None


def _lenovo_synthetic_port_document(
    client: Any,
    adapter_base: str,
    port_index: int,
    client_port_path: str,
) -> Optional[dict]:
    if client is None or port_index < 1:
        return None
    adapter = redfish_get_json(client, adapter_base)
    if not isinstance(adapter, dict):
        return None
    pcie_uri = _primary_pcie_device_uri(adapter)
    if not pcie_uri:
        return None
    fn_uris = _lenovo_sorted_network_pcie_function_uris(client, pcie_uri)
    if not fn_uris or port_index > len(fn_uris):
        return None
    fn = redfish_get_json(client, fn_uris[port_index - 1])
    if not isinstance(fn, dict):
        return None
    st = fn.get("Status")
    if not isinstance(st, dict):
        st = {"State": None, "Health": None}
    name = fn.get("Name")
    if not (isinstance(name, str) and name.strip()):
        name = f"Physical Port {port_index}"
    port_path = client_port_path.rstrip("/")
    return {
        "@odata.context": "/redfish/v1/$metadata#Port.Port",
        "@odata.id": port_path,
        "@odata.type": LenovoChassisPortNormalizer().field_map()["@odata.type"],
        "Id": str(port_index),
        "Name": name,
        "PortId": str(port_index),
        "Description": "A Network Port represents a discrete physical port capable of connecting to a network.",
        # No LinkStatus or link technology: this document is built from a PCIe
        # function, which does not say whether the port is up or what it carries.
        "LinkNetworkTechnology": None,
        "Status": st,
        "Oem": {"Redpool": {"PhysicalPortNumber": str(port_index)}},
    }


def _lenovo_ports_matches(path: str) -> bool:
    if "/Chassis/" not in path or "/NetworkAdapters/" not in path:
        return False
    return "Ports" in path.split("/")


def _lenovo_ports_backend_path(path: str) -> str:
    return path


def _lenovo_ports_response_rewrite(path: str) -> Tuple[str, str]:
    return path, path


def _fill_lenovo_port_names(body: Any, client: Any) -> Any:
    """Copy Lenovo port number and MAC onto Port properties.

    The client URL is ``Ports/{id}`` and is often absent on the BMC, so the proxy
    does not run the resource normalizer. Keep the Port document and fill ``PortId``
    and ``Ethernet.AssociatedMACAddresses`` from it.
    """
    if not isinstance(body, dict):
        return body
    otype = body.get("@odata.type") or ""
    if not otype.startswith("#Port.") or "Collection" in otype:
        return body
    ctx = NormalizationContext(
        data=body,
        client=client,
        logger=_LOG,
        vendor="Lenovo",
    )
    mapped = normalize_resource(LenovoChassisPortNormalizer(), ctx)
    for key in ("PortId", "LinkNetworkTechnology", "CurrentSpeedGbps"):
        if key in mapped and body.get(key) in (None, ""):
            body[key] = mapped[key]
    if "LinkStatus" in mapped:
        body["LinkStatus"] = mapped["LinkStatus"]
    else:
        body.pop("LinkStatus", None)
    mapped_eth = mapped.get("Ethernet")
    if isinstance(mapped_eth, dict):
        macs = mapped_eth.get("AssociatedMACAddresses")
        if isinstance(macs, list) and macs:
            ethernet = body.get("Ethernet")
            if not isinstance(ethernet, dict):
                ethernet = {}
                body["Ethernet"] = ethernet
            if not ethernet.get("AssociatedMACAddresses"):
                ethernet["AssociatedMACAddresses"] = macs
    for key in _NETWORK_PORT_NAMES:
        body.pop(key, None)
    return prepare_port_document(body)


def _normalized_lenovo_port(body: Dict[str, Any], client: Any, path: str) -> Any:
    """Normalize a native Port member here; the proxy does not normalize it again."""
    otype = body.get("@odata.type") or ""
    if not otype.startswith("#Port.") or "Collection" in otype:
        return body
    ctx = NormalizationContext(
        data=prepare_port_document(body),
        client=client,
        logger=_LOG,
        vendor="Lenovo",
        resource_path=path,
    )
    return normalize_resource(LenovoChassisPortNormalizer(), ctx)


def _lenovo_ports_after_200_merge(call: RewriteCall, body: Any) -> Any:
    """Filter blank member links; fill empty ``Ports`` collections from PCIe functions."""
    client, backend_path = call.client, call.backend_path
    if not isinstance(body, dict):
        return body
    members = body.get("Members")
    if not isinstance(members, list) or not members:
        filled = _lenovo_fill_empty_port_collection(client, backend_path, body)
        if filled is not None:
            body = filled
            members = body.get("Members")
    if not isinstance(members, list) or not members:
        return _normalized_lenovo_port(body, client, call.path)
    out_members: list[Any] = []
    changed = False
    for raw in members:
        if not isinstance(raw, dict):
            out_members.append(raw)
            continue
        m = dict(raw)
        oid = m.get("@odata.id")
        if isinstance(oid, str) and oid.strip():
            out_members.append(m)
            continue
        changed = True
    if not changed:
        return body
    merged = dict(body)
    merged["Members"] = out_members
    if "Members@odata.count" in merged:
        try:
            merged["Members@odata.count"] = len(out_members)
        except (TypeError, ValueError):
            pass
    return merged


def _lenovo_ports_on_backend_error(
    call: RewriteCall, resp_status: int
) -> Optional[Tuple[Any, int]]:
    client, path, backend_path = call.client, call.path, call.backend_path
    if client is None or resp_status not in (404, 0):
        return None
    adapter_base = _adapter_base_from_ports_related_path(
        backend_path,
    ) or _adapter_base_from_ports_related_path(path)
    if not adapter_base:
        return None
    port_index = _lenovo_port_index_from_paths(path, backend_path)
    if port_index is None or port_index < 1:
        return None
    doc = _lenovo_synthetic_port_document(client, adapter_base, port_index, path)
    if doc is None:
        return None
    return (_fill_lenovo_port_names(doc, client), 200)


def _lenovo_ports_should_normalize_single(path: str, backend_path: str) -> bool:
    # Port members are normalized in after_200_merge; collections are not Ports.
    del path, backend_path
    return False


def register_lenovo_ports_request_rewrite() -> None:
    if _registration_state["done"]:
        return
    _registration_state["done"] = True
    register_request_rewrite(
        RequestRewriteRule(
            vendor="Lenovo",
            matches=_lenovo_ports_matches,
            get_backend_path=_lenovo_ports_backend_path,
            get_response_rewrite=_lenovo_ports_response_rewrite,
            on_backend_error=_lenovo_ports_on_backend_error,
            after_200_merge=_lenovo_ports_after_200_merge,
            should_normalize_single=_lenovo_ports_should_normalize_single,
        )
    )


register_lenovo_ports_request_rewrite()
