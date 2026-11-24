# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE: serve ``Chassis/{id}/NetworkAdapters/{id}/Ports`` (DMTF ``#Port``).

Some Gen10 iLO builds (e.g. DL380) expose NIC inventory under
``Systems/.../BaseNetworkAdapters`` with embedded ``PhysicalPorts``, while
``Chassis/.../NetworkAdapters`` has no usable ports. redfish-inventory-exporter reads
``Ports`` only, so for those chassis we rewrite ``Ports`` requests to
BaseNetworkAdapters and synthesize a ``Ports`` collection and ``#Port`` members from
``PhysicalPorts``.

When the chassis ports are usable, requests pass through unchanged, and phantom
``NetworkPorts`` members are dropped. ``NetworkPorts`` is never rewritten.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any, Dict, List, Optional, Tuple

from redpool.redfish_client import redfish_get_json

from ..._shared.link_technology import ethernet_from_mac_address
from ...apply import normalize_resource
from ...request_rewrites import (
    RequestRewriteRule,
    RewriteCall,
    register_request_rewrite,
)
from ...types import NormalizationContext
from ..network_ports.base import canonicalize_port_link_status
from ..ports.base import PORT_COLLECTION_MAPPING, BasePortNormalizer

_registration_done = False
_log = logging.getLogger(__name__)

# Resolve→merge cycle memo for hpe_chassis_network_adapters_usable.
# Fresh dict is installed in resolve_backend; after_200_merge reuses it.
_usable_memo: contextvars.ContextVar[Optional[Dict[Tuple[int, str], bool]]] = (
    contextvars.ContextVar("hpe_chassis_network_adapters_usable_memo", default=None)
)


def _path_parts(path: str) -> List[str]:
    return [p for p in path.split("/") if p]


def _adapter_has_usable_ports(client: Any, adapter_odata_id: str) -> bool:
    """True if the Ports collection under this adapter has at least one member."""
    base = adapter_odata_id.rstrip("/")
    for suffix in ("/Ports",):
        try:
            coll = redfish_get_json(client, base + suffix)
        except Exception:
            _log.debug(
                "HPE chassis adapter port probe failed for %s%s",
                base,
                suffix,
                exc_info=True,
            )
            continue
        if not isinstance(coll, dict):
            continue
        members = coll.get("Members") or []
        if any(
            isinstance(m, dict) and (m.get("@odata.id") or "").strip() for m in members
        ):
            return True
    return False


def _begin_usable_memo() -> None:
    """Start a fresh usability memo for this resolve→after_200_merge cycle."""
    _usable_memo.set({})


def hpe_chassis_network_adapters_usable(client: Any, chassis_id: str) -> bool:
    """True if Chassis NetworkAdapters has members *and* at least one has ports.

    Gen10 iLO often publishes a chassis adapter stub (e.g. ``DC07A000``) whose
    Ports collection is empty while Systems BaseNetworkAdapters carries
    PhysicalPorts. Treat that as unusable so we synthesize from BaseNetwork.

    Results are memoized per ``(id(client), chassis_id)`` for the current
    resolve→merge cycle (see ``_begin_usable_memo``), not process-wide.
    """
    key = (id(client), chassis_id)
    memo = _usable_memo.get()
    if memo is None:
        memo = {}
        _usable_memo.set(memo)
    cached = memo.get(key)
    if cached is not None:
        return cached

    usable = False
    try:
        coll = redfish_get_json(
            client, f"/redfish/v1/Chassis/{chassis_id}/NetworkAdapters"
        )
        if coll:
            members = coll.get("Members") or []
            adapter_ids = [
                (m.get("@odata.id") or "").strip()
                for m in members
                if isinstance(m, dict) and (m.get("@odata.id") or "").strip()
            ]
            if adapter_ids:
                usable = any(
                    _adapter_has_usable_ports(client, oid) for oid in adapter_ids
                )
    except Exception:
        usable = False
    memo[key] = usable
    return usable


def _chassis_id_from_network_path(path: str) -> Optional[str]:
    parts = _path_parts(path)
    try:
        i = parts.index("Chassis")
        if i + 1 < len(parts):
            return parts[i + 1]
    except ValueError:
        pass
    return None


def _split_network_adapters_segments(path: str) -> Optional[Tuple[str, str, List[str]]]:
    """Return (chassis_id, adapter_id or \"\", segments_after_networkadapters)."""
    cid = _chassis_id_from_network_path(path)
    if not cid:
        return None
    parts = _path_parts(path)
    try:
        i = parts.index("NetworkAdapters")
    except ValueError:
        return None
    after = parts[i + 1 :]
    adapter_id = after[0] if after else ""
    rest = after[1:] if len(after) > 1 else []
    return cid, adapter_id, rest


def drop_phantom_network_port_members(body: Any) -> Any:
    """Omit ``Members`` entries with missing ``@odata.id``; fix count."""
    if not isinstance(body, dict):
        return body
    members = body.get("Members")
    if not isinstance(members, list) or not members:
        return body
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


def _is_hpe_base_network_adapter_doc(body: Dict[str, Any]) -> bool:
    odt = body.get("@odata.type")
    if isinstance(odt, str) and "HpeBaseNetworkAdapter" in odt:
        return True
    return isinstance(body.get("PhysicalPorts"), list)


def _standard_base_network_adapter(
    path: str,
    body: Dict[str, Any],
    client: Any,
) -> Dict[str, Any]:
    """Apply the HPE NetworkAdapter normalizer when the body is a BaseNetworkAdapter.

    The client path is not on the BMC, so the proxy does not run that normalizer.
    """
    if not _is_hpe_base_network_adapter_doc(body) or "Members" in body:
        return body
    parts = _path_parts(path)
    try:
        na_idx = parts.index("NetworkAdapters")
    except ValueError:
        return body
    if na_idx != len(parts) - 2:
        return body
    from .hpe import HPEChassisNetworkAdapterNormalizer

    ctx = NormalizationContext(
        data=body,
        client=client,
        logger=_log,
        vendor="HPE",
        resource_path=path,
    )
    return normalize_resource(HPEChassisNetworkAdapterNormalizer(), ctx)


def _promote_base_network_adapter_collection(body: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(body)
    merged["@odata.type"] = "#NetworkAdapterCollection.NetworkAdapterCollection"
    merged["@odata.context"] = (
        "/redfish/v1/$metadata#NetworkAdapterCollection.NetworkAdapterCollection"
    )
    merged.setdefault("Name", "NetworkAdapterCollection")
    merged.setdefault("Description", "Collection of Network Adapters")
    return merged


def _physical_to_port(
    port: Dict[str, Any],
    port_odata_id: str,
    index: int,
) -> Dict[str, Any]:
    mac = port.get("MacAddress")
    assoc: List[str] = []
    if isinstance(mac, str) and mac.strip():
        assoc = [mac.strip()]
    speed = port.get("SpeedMbps")
    cur_mbps: Optional[int]
    if isinstance(speed, int):
        cur_mbps = speed
    elif isinstance(speed, str) and speed.strip().isdigit():
        cur_mbps = int(speed.strip(), 10)
    else:
        cur_mbps = None
    cur_gbps: Any = None
    if cur_mbps:
        cur_gbps = cur_mbps / 1000
        if cur_gbps == int(cur_gbps):
            cur_gbps = int(cur_gbps)
    name_raw = port.get("Name")
    name = (
        name_raw.strip()
        if isinstance(name_raw, str) and name_raw.strip()
        else f"Port {index}"
    )
    st = port.get("Status")
    if not isinstance(st, dict):
        st = {}
    st_out = dict(st)
    if not (isinstance(st_out.get("State"), str) and st_out["State"].strip()):
        st_out["State"] = None
    body = {
        "@odata.context": "/redfish/v1/$metadata#Port.Port",
        "@odata.id": port_odata_id,
        "@odata.type": BasePortNormalizer().field_map()["@odata.type"],
        "Id": str(index),
        "Name": name,
        "PortId": str(index),
        "LinkStatus": canonicalize_port_link_status(port.get("LinkStatus")),
        "CurrentSpeedGbps": cur_gbps,
        "LinkNetworkTechnology": ethernet_from_mac_address(mac),
        "Status": st_out,
        "Ethernet": {"AssociatedMACAddresses": assoc} if assoc else {},
        "Oem": port.get("Oem") if isinstance(port.get("Oem"), dict) else {},
    }
    for key in ("LinkStatus", "CurrentSpeedGbps", "LinkNetworkTechnology"):
        if body[key] is None:
            del body[key]
    return body


def _synthesize_ports_from_adapter(
    adapter_body: Dict[str, Any],
    request_path: str,
) -> Dict[str, Any]:
    ports = adapter_body.get("PhysicalPorts")
    if not isinstance(ports, list):
        ports = []
    coll_id = request_path.rstrip("/")
    members = [{"@odata.id": f"{coll_id}/{i}"} for i in range(1, len(ports) + 1)]
    return {
        "@odata.context": "/redfish/v1/$metadata#PortCollection.PortCollection",
        "@odata.id": coll_id,
        "@odata.type": PORT_COLLECTION_MAPPING["@odata.type"],
        "Description": "Collection of Ports",
        "Name": "Ports Collection",
        "Members": members,
        "Members@odata.count": len(members),
        "Oem": {},
    }


def _synthesize_port_member(
    adapter_body: Dict[str, Any],
    request_path: str,
    port_id_str: str,
) -> Dict[str, Any]:
    ports = adapter_body.get("PhysicalPorts")
    if not isinstance(ports, list) or not ports:
        return adapter_body
    try:
        idx = int(str(port_id_str).strip(), 10)
    except ValueError:
        return adapter_body
    if idx < 1 or idx > len(ports):
        return adapter_body
    p = ports[idx - 1]
    if not isinstance(p, dict):
        return adapter_body
    return _physical_to_port(p, request_path.rstrip("/"), idx)


def _hpe_chassis_network_matches(path: str) -> bool:
    return "/Chassis/" in path and "/NetworkAdapters" in path


def _hpe_chassis_network_resolve_backend(
    client: Any, path: str
) -> Tuple[str, str, str]:
    _begin_usable_memo()
    cid = _chassis_id_from_network_path(path)
    if not cid or client is None:
        return (path, path, path)

    usable = hpe_chassis_network_adapters_usable(client, cid)

    if usable:
        return (path, path, path)

    base_from = f"/redfish/v1/Systems/{cid}/BaseNetworkAdapters"
    base_to = f"/redfish/v1/Chassis/{cid}/NetworkAdapters"

    parsed = _split_network_adapters_segments(path)
    if not parsed:
        return (path, path, path)
    _cid, adapter_id, rest = parsed

    if not adapter_id:
        return (base_from, base_from, base_to)

    backend_member = f"{base_from}/{adapter_id}"
    if not rest:
        return (backend_member, base_from, base_to)

    if rest[0].casefold() != "ports":
        return (path, path, path)

    return (backend_member, base_from, base_to)


def _hpe_chassis_network_after_200_merge(call: RewriteCall, body: Any) -> Any:
    client, path = call.client, call.path
    if not isinstance(body, dict):
        return body
    from ..network_ports.base import prepare_port_document

    prepare_port_document(body)
    otype = body.get("@odata.type") or ""
    if (
        isinstance(otype, str)
        and otype.startswith("#Port.")
        and "Collection" not in otype
    ):
        body.pop("Settings", None)
        # Port Settings retains its payload and bypasses the Port member field map.
        if "LinkStatus" in body:
            status = canonicalize_port_link_status(body["LinkStatus"])
            if status is None:
                del body["LinkStatus"]
            else:
                body["LinkStatus"] = status
    cid = _chassis_id_from_network_path(path)
    if client is None or not cid:
        return body

    usable = hpe_chassis_network_adapters_usable(client, cid)

    # Blank member links (``@odata.id: ""``) are placeholders, not ports.
    if usable and path.rstrip("/").rsplit("/", 1)[-1] in ("NetworkPorts", "Ports"):
        return drop_phantom_network_port_members(body)

    if usable:
        return _standard_base_network_adapter(path, body, client)

    parts = _path_parts(path)
    try:
        na_idx = parts.index("NetworkAdapters")
    except ValueError:
        return body

    if na_idx == len(parts) - 1:
        return _promote_base_network_adapter_collection(body)

    if (
        len(parts) >= na_idx + 3
        and parts[na_idx + 2].casefold() == "ports"
        and _is_hpe_base_network_adapter_doc(body)
    ):
        if len(parts) == na_idx + 3:
            return _synthesize_ports_from_adapter(body, path)
        if len(parts) == na_idx + 4:
            return _synthesize_port_member(body, path, parts[na_idx + 3])

    if _is_hpe_base_network_adapter_doc(body) and "Members" in body:
        return _promote_base_network_adapter_collection(body)

    return _standard_base_network_adapter(path, body, client)


def _hpe_chassis_network_should_normalize_single(path: str, backend_path: str) -> bool:
    # Synthesized from BaseNetworkAdapters. The member is already a Port at the
    # Redpool version; the Port field map must not replace it.
    if "/BaseNetworkAdapters/" in backend_path and "/Ports/" in path:
        return False
    p = _path_parts(path)
    try:
        i = p.index("NetworkAdapters")
    except ValueError:
        return False
    after = p[i + 1 :]
    if not after:
        return False
    if len(after) == 1:
        # A BaseNetworkAdapter is normalized in after_200_merge.
        return "/BaseNetworkAdapters/" not in backend_path
    if len(after) >= 2 and after[1].casefold() in ("networkports", "ports"):
        if len(after) == 2:
            return False
        return bool(after[2]) and after[2].casefold() not in ("networkports", "ports")
    return False


def register_hpe_chassis_network_request_rewrite() -> None:
    global _registration_done
    if _registration_done:
        return
    _registration_done = True
    register_request_rewrite(
        RequestRewriteRule(
            vendor="HPE",
            matches=_hpe_chassis_network_matches,
            get_backend_path=lambda p: p,
            get_response_rewrite=lambda p: (p, p),
            resolve_backend=_hpe_chassis_network_resolve_backend,
            after_200_merge=_hpe_chassis_network_after_200_merge,
            should_normalize_single=_hpe_chassis_network_should_normalize_single,
        )
    )


register_hpe_chassis_network_request_rewrite()
