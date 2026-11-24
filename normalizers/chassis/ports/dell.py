# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell: serve ``NetworkAdapters/{id}/Ports`` when the iDRAC has only ``NetworkPorts``.

Older iDRAC firmware (PowerEdge R630 family) lists ``NetworkPorts`` on each adapter and
has no ``Ports`` collection. ``redfish-inventory-exporter`` reads ``Ports`` only, so:

- an adapter gets a ``Ports`` link to its own ``Ports`` collection when the BMC omits
  it;
- a ``Ports`` request is served from the BMC's ``NetworkPorts``, and each member is
  converted to a DMTF ``#Port`` document. A BMC that already has ``Ports`` is passed
  through unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from redpool.redfish_client import redfish_get_json

from ..._shared.dell_nic_product import nic_product_name
from ...systems.ethernet_interfaces.dell import dell_lnk_speed_to_speed_mbps

from normalizers._shared.dell_link_status import canonicalize_dell_oem_link_status

from ...request_rewrites import (
    RequestRewriteRule,
    RewriteCall,
    register_request_rewrite,
)
from ...types import NormalizationContext
from ...optional import omit_if_null
from ..network_ports.base import (
    canonicalize_port_link_status,
    effective_port_current_speed_gbps,
    effective_port_id,
)
from ..network_ports.dell import (
    GENERIC_PORT_NAMES,
    effective_network_port_name,
    effective_network_port_status,
    oem_attrs,
    parse_chassis_network_port_path,
    port_number_from_id,
    prefetch_dell_network_port_oem,
    prefetch_network_port_pcie_display,
    prefetch_network_port_pcie_status,
)
from .base import PORT_COLLECTION_MAPPING, BasePortNormalizer

_PORTS_SEGMENT = "Ports"
_NETWORK_PORTS_SEGMENT = "NetworkPorts"


def _segments(path: str) -> List[str]:
    return [p for p in path.split("/") if p]


def _is_adapter_path(path: str) -> bool:
    parts = _segments(path)
    return len(parts) >= 2 and parts[-2] == "NetworkAdapters" and "Ports" not in parts


def _is_ports_path(path: str) -> bool:
    """``.../NetworkAdapters/{id}/Ports`` or ``.../Ports/{member}``."""
    parts = _segments(path)
    if "NetworkAdapters" not in parts:
        return False
    i = parts.index("NetworkAdapters")
    rest = parts[i + 1 :]
    return len(rest) in (2, 3) and rest[1] == _PORTS_SEGMENT


def _adapter_base(path: str) -> str:
    parts = _segments(path)
    i = parts.index("NetworkAdapters")
    return "/" + "/".join(parts[: i + 2])


def _has_members(collection: Dict[str, Any]) -> bool:
    members = collection.get("Members")
    return isinstance(members, list) and any(
        isinstance(m, dict) and (m.get("@odata.id") or "").strip() for m in members
    )


def _gbps_from_mbps(mbps: Any) -> Any:
    if isinstance(mbps, bool) or not isinstance(mbps, (int, float)) or mbps <= 0:
        return None
    gbps = mbps / 1000
    return int(gbps) if gbps == int(gbps) else gbps


def port_from_network_port(np: Dict[str, Any], odata_id: str) -> Dict[str, Any]:
    """Convert a NetworkPort document to a Port document, keeping only what it reports."""
    out: Dict[str, Any] = {
        "@odata.context": "/redfish/v1/$metadata#Port.Port",
        "@odata.id": odata_id,
        "@odata.type": BasePortNormalizer().field_map()["@odata.type"],
    }
    for key in ("Id", "Name", "Description", "Status", "Oem"):
        if key in np:
            out[key] = np[key]
    number = np.get("PhysicalPortNumber")
    if number not in (None, ""):
        out["PortId"] = str(number)
    status = canonicalize_port_link_status(np.get("LinkStatus"))
    if status is not None:
        out["LinkStatus"] = status
    speed = _gbps_from_mbps(np.get("CurrentLinkSpeedMbps"))
    if speed is not None:
        out["CurrentSpeedGbps"] = speed
    tech = np.get("ActiveLinkTechnology")
    if isinstance(tech, str) and tech.strip():
        out["LinkNetworkTechnology"] = tech.strip()
    macs = [
        a.strip()
        for a in (np.get("AssociatedNetworkAddresses") or [])
        if isinstance(a, str) and a.strip()
    ]
    if macs:
        out["Ethernet"] = {"AssociatedMACAddresses": macs}
    return out


def _port_collection(body: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(body)
    out["@odata.context"] = "/redfish/v1/$metadata#PortCollection.PortCollection"
    out["@odata.type"] = PORT_COLLECTION_MAPPING["@odata.type"]
    out["Name"] = "Ports Collection"
    out["Description"] = "Collection of Ports"
    return out


def _dell_ports_resolve_backend(client: Any, path: str) -> Tuple[str, str, str]:
    if _is_adapter_path(path):
        return (path, path, path)
    base = _adapter_base(path)
    try:
        ports = redfish_get_json(client, base + "/" + _PORTS_SEGMENT)
    except Exception:
        # A missing collection is the case this rule handles, so treat errors as absent.
        ports = None
    if isinstance(ports, dict) and _has_members(ports):
        return (path, path, path)
    backend = path.replace("/" + _PORTS_SEGMENT, "/" + _NETWORK_PORTS_SEGMENT, 1)
    from_prefix = base + "/" + _NETWORK_PORTS_SEGMENT
    to_prefix = base + "/" + _PORTS_SEGMENT
    return (backend, from_prefix, to_prefix)


def _dell_ports_after_200_merge(call: RewriteCall, body: Any) -> Any:
    path, backend_path = call.path, call.backend_path
    if not isinstance(body, dict):
        return body
    if _is_adapter_path(path):
        if "Ports" in body or not isinstance(body.get("NetworkPorts"), dict):
            return body
        # ``Ports`` is a NetworkAdapter property from v1_8. The iDRAC payload is v1_1_0,
        # so the adapter is stamped with the first version that has the link.
        merged = dict(body)
        merged["@odata.type"] = "#NetworkAdapter.v1_8_1.NetworkAdapter"
        merged["Ports"] = {"@odata.id": path.rstrip("/") + "/" + _PORTS_SEGMENT}
        return merged
    if backend_path == path:
        return body
    otype = body.get("@odata.type") or ""
    if not isinstance(otype, str):
        return body
    if otype.startswith("#NetworkPortCollection."):
        return _port_collection(body)
    if otype.startswith("#NetworkPort."):
        return port_from_network_port(body, path)
    return body


def _dell_ports_should_normalize_single(path: str, backend_path: str) -> bool:
    # Converted members are already Port documents. Native Ports members are normalized.
    return backend_path == path


def register_dell_ports_request_rewrite() -> None:
    register_request_rewrite(
        RequestRewriteRule(
            vendor="Dell",
            matches=lambda p: _is_adapter_path(p) or _is_ports_path(p),
            get_backend_path=lambda p: p,
            get_response_rewrite=lambda p: (p, p),
            resolve_backend=_dell_ports_resolve_backend,
            after_200_merge=_dell_ports_after_200_merge,
            should_normalize_single=_dell_ports_should_normalize_single,
        )
    )


register_dell_ports_request_rewrite()


_PRODUCT_NAME_KEY = "_dell_port_product_name"


def prefetch_dell_port_product_name(ctx: NormalizationContext) -> None:
    """Read ``DellNIC.ProductName`` from the port's NetworkDeviceFunction.

    The function id is the port id, or the port id with a partition suffix
    (``NIC.Embedded.1-1`` is served as ``NIC.Embedded.1-1-1`` on newer iDRACs).
    """
    ctx.prefetched.pop(_PRODUCT_NAME_KEY, None)
    if ctx.client is None:
        return
    parsed = parse_chassis_network_port_path(ctx.odata_id)
    port_id = ctx.data.get("Id")
    if not parsed or not isinstance(port_id, str) or parsed[2] != port_id:
        return
    chassis_prefix, adapter_id, _ = parsed
    functions = f"{chassis_prefix}/NetworkAdapters/{adapter_id}/NetworkDeviceFunctions"
    name = nic_product_name(
        ctx.client, [f"{functions}/{port_id}-1", f"{functions}/{port_id}"]
    )
    if name:
        ctx.prefetched[_PRODUCT_NAME_KEY] = name


def _dell_port_name(ctx: NormalizationContext) -> Any:
    """BMC name, else OEM DeviceName, else PCIe function name, else the NIC product name."""
    name = effective_network_port_name(ctx)
    if isinstance(name, str) and name.strip().lower() not in GENERIC_PORT_NAMES:
        return name
    product = ctx.prefetched.get(_PRODUCT_NAME_KEY)
    return product if isinstance(product, str) and product else name


def _bmc_reports_no_state(ctx: NormalizationContext) -> bool:
    """True when the iDRAC gave the port no Status at all (it could not read the port).

    Such a port also gets placeholder values (LinkStatus "LinkDown", speed 0), so those are
    not trusted. A port that has a Status is left as the iDRAC reports it, because the
    OEM attributes can disagree with a port that is up.
    """
    status = ctx.data.get("Status")
    if not isinstance(status, dict):
        return True
    return not any(status.get(key) for key in ("State", "Health", "HealthRollup"))


def _dell_port_link_status(ctx: NormalizationContext) -> Any:
    if _bmc_reports_no_state(ctx):
        mapped = canonicalize_dell_oem_link_status(oem_attrs(ctx).get("LinkStatus"))
        if mapped:
            return canonicalize_port_link_status(mapped)
    return canonicalize_port_link_status(ctx.data.get("LinkStatus"))


def _dell_port_speed_gbps(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("CurrentSpeedGbps")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw != 0:
        return raw
    mbps = dell_lnk_speed_to_speed_mbps(oem_attrs(ctx).get("LnkSpeed"))
    if mbps is not None:
        gbps = mbps / 1000
        return int(gbps) if gbps == int(gbps) else gbps
    return effective_port_current_speed_gbps(ctx)


def _dell_port_id(ctx: NormalizationContext) -> Any:
    from_id = port_number_from_id(ctx, ctx.data.get("PortId"))
    if isinstance(from_id, str) and from_id.strip():
        return from_id
    return effective_port_id(ctx)


class DellChassisPortNormalizer(BasePortNormalizer):
    """Dell ``Port``: the corrections the iDRAC needs, which the NetworkPort normalizer had.

    - Name: iDRAC calls every port "Network Inteface Card(NIC) Port View". The real model
      comes from the OEM ``DeviceName``, the adapter's PCIe function, or ``DellNIC``.
    - Status: filled from the chassis PCIe device when the iDRAC reports none.
    - LinkStatus and speed: from the OEM attributes when the iDRAC could not read the port.
    - PortId: the index in the port's Id, when the iDRAC repeats the PCIe slot instead.
    """

    def prefetch(self, ctx: NormalizationContext) -> None:
        # These lookups are optional enrichments. If one fails, skip it: letting the error
        # escape would discard the whole port document.
        for lookup in (
            prefetch_dell_network_port_oem,
            prefetch_dell_port_product_name,
            prefetch_network_port_pcie_status,
        ):
            try:
                lookup(ctx)
            except Exception:
                ctx.logger.debug("Dell port lookup unavailable", exc_info=True)
        prefetch_network_port_pcie_display(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Name"] = _dell_port_name
        m["Status"] = effective_network_port_status
        m["LinkStatus"] = omit_if_null(_dell_port_link_status)
        m["CurrentSpeedGbps"] = _dell_port_speed_gbps
        m["PortId"] = _dell_port_id
        return m
