# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Chassis NetworkPort normalizer (under NetworkAdapter)."""

from __future__ import annotations

from typing import Any, Dict

from ..._shared.link_technology import ethernet_from_mac_address
from ...base import ResourceNormalizer
from ...optional import OMIT, omit_if_null, optional
from ...types import NormalizationContext


def _data(ctx: NormalizationContext, key: str, default: Any = None) -> Any:
    return ctx.data.get(key, default)


_LLDP_OMIT_IF_BLANK = ("PortId", "ManagementAddressIPv4", "ManagementAddressMAC")


def _sanitize_port_ethernet(ethernet: Dict[str, Any]) -> None:
    """Drop LLDP values Port.v1_20_0 still rejects."""
    if ethernet.get("LLDPEnabled") is None and "LLDPEnabled" in ethernet:
        del ethernet["LLDPEnabled"]
    for side in ("LLDPReceive", "LLDPTransmit"):
        block = ethernet.get(side)
        if not isinstance(block, dict):
            continue
        for key in _LLDP_OMIT_IF_BLANK:
            if block.get(key) == "":
                del block[key]


def prepare_port_document(body: Dict[str, Any]) -> Dict[str, Any]:
    """Set the Port schema version and rename ``Infiniband`` on a passthrough body."""
    otype = body.get("@odata.type") or ""
    if (
        not isinstance(otype, str)
        or not otype.startswith("#Port.")
        or "Collection" in otype
    ):
        return body
    from ..ports.base import BasePortNormalizer

    body["@odata.type"] = BasePortNormalizer().field_map()["@odata.type"]
    if "Infiniband" in body:
        if "InfiniBand" not in body:
            body["InfiniBand"] = body["Infiniband"]
        del body["Infiniband"]
    ethernet = body.get("Ethernet")
    if isinstance(ethernet, dict):
        _sanitize_port_ethernet(ethernet)
    return body


def _nonempty_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def effective_port_link_network_technology(ctx: NormalizationContext) -> Any:
    return effective_network_port_active_link_technology(ctx)


def effective_port_current_speed_gbps(ctx: NormalizationContext) -> Any:
    """``Port.CurrentSpeedGbps``, or ``CurrentLinkSpeedMbps`` converted from Mbps."""
    raw = ctx.data.get("CurrentSpeedGbps")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw != 0:
        return raw
    mbps = ctx.data.get("CurrentLinkSpeedMbps")
    if isinstance(mbps, bool) or mbps is None:
        return OMIT
    try:
        speed = float(mbps)
    except (TypeError, ValueError):
        return OMIT
    if speed <= 0:
        return OMIT
    gbps = speed / 1000.0
    if gbps == int(gbps):
        return int(gbps)
    return gbps


def effective_port_id(ctx: NormalizationContext) -> Any:
    """``Port.PortId``, falling back to ``PhysicalPortNumber``."""
    port_id = _nonempty_str(ctx.data.get("PortId"))
    if port_id is not None:
        return port_id
    physical = ctx.data.get("PhysicalPortNumber")
    text = _nonempty_str(physical)
    if text is not None:
        return text
    if (
        isinstance(physical, (int, float))
        and not isinstance(physical, bool)
        and physical == int(physical)
    ):
        return str(int(physical))
    return OMIT


def _macs_present(value: Any) -> bool:
    return isinstance(value, list) and any(
        isinstance(item, str) and item.strip() for item in value
    )


def port_ethernet(ctx: NormalizationContext, promoted_macs: Any = None) -> Any:
    """Copy ``Ethernet`` and keep MACs that arrived under the NetworkPort name."""
    ethernet = ctx.data.get("Ethernet")
    body = dict(ethernet) if isinstance(ethernet, dict) else {}
    for side in ("LLDPReceive", "LLDPTransmit"):
        block = body.get(side)
        if isinstance(block, dict):
            body[side] = dict(block)
    _sanitize_port_ethernet(body)
    if not _macs_present(body.get("AssociatedMACAddresses")):
        addresses = ctx.data.get("AssociatedNetworkAddresses")
        if _macs_present(addresses):
            body["AssociatedMACAddresses"] = [
                item.strip()
                for item in addresses
                if isinstance(item, str) and item.strip()
            ]
        elif _macs_present(promoted_macs):
            body["AssociatedMACAddresses"] = [
                item.strip()
                for item in promoted_macs
                if isinstance(item, str) and item.strip()
            ]
    if not body:
        return OMIT
    return body


def effective_network_port_active_link_technology(ctx: NormalizationContext) -> Any:
    """``NetworkPort.ActiveLinkTechnology`` or DMTF ``#Port.LinkNetworkTechnology`` (Lenovo/XCC)."""
    alt = _data(ctx, "ActiveLinkTechnology")
    if isinstance(alt, str) and alt.strip():
        return alt.strip()
    if alt is not None and not isinstance(alt, str):
        return alt
    lnt = _data(ctx, "LinkNetworkTechnology")
    if isinstance(lnt, str) and lnt.strip():
        return lnt.strip()
    # No technology reported: a 48-bit MAC on the port means Ethernet.
    mac = _data(ctx, "MacAddress")
    if mac is None:
        assoc = _data(ctx, "AssociatedNetworkAddresses")
        mac = assoc[0] if isinstance(assoc, list) and assoc else None
    inferred = ethernet_from_mac_address(mac)
    return inferred if inferred is not None else alt


def canonicalize_ethernet_link_status(value: Any) -> Any:
    """Normalize link status strings to ``EthernetInterface.LinkStatus`` values.

    Maps legacy ``Up``/``Down``, ``LinkUp``/``LinkDown``/``NoLink``, and common OEM
    strings (``Connected`` / ``Disconnected``) to ``LinkUp``, ``LinkDown``, or
    ``NoLink``. Passes through unknown vendor strings unchanged.
    """
    if not isinstance(value, str):
        return value
    v = value.strip()
    if not v:
        return value
    lower = v.casefold()
    if lower in ("up", "linkup", "link up", "connected"):
        return "LinkUp"
    if lower in ("down", "linkdown", "link down", "disconnected"):
        return "LinkDown"
    if lower in ("nolink", "no link", "no_link"):
        return "NoLink"
    if lower in ("linknegotiating", "link negotiating", "negotiating"):
        return "LinkNegotiating"
    return value


def canonicalize_port_link_status(value: Any) -> Any:
    """Normalize link status strings to ``Port.LinkStatus`` values.

    ``#Port`` allows ``LinkUp``, ``LinkDown``, ``NoLink``, ``Starting``, and
    ``Training``. NetworkPort ``Up`` / ``Down`` map onto ``LinkUp`` /
    ``LinkDown``. ``NoLink`` stays ``NoLink``. Any other string is omitted.
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    lower = v.casefold()
    if lower in ("up", "linkup", "link up", "connected"):
        return "LinkUp"
    if lower in ("down", "linkdown", "link down", "disconnected"):
        return "LinkDown"
    if lower in ("nolink", "no link", "no_link"):
        return "NoLink"
    if lower == "starting":
        return "Starting"
    if lower in ("training", "linknegotiating", "link negotiating", "negotiating"):
        return "Training"
    return None


def effective_link_status(ctx: NormalizationContext) -> Any:
    """NetworkPort.LinkStatus: Up or Down, with the NetworkPort enum."""
    return canonicalize_network_port_link_status(_data(ctx, "LinkStatus"))


def port_link_status(ctx: NormalizationContext) -> Any:
    """Port.LinkStatus: the Port enum (LinkUp, LinkDown, NoLink, Starting, Training)."""
    return canonicalize_port_link_status(_data(ctx, "LinkStatus"))


def canonicalize_network_port_link_status(value: Any) -> Any:
    """Normalize link status strings to ``NetworkPort.LinkStatus`` values.

    ``#NetworkPort.v1_4_1.NetworkPort`` allows ``Down``, ``Up``, ``Starting``, and
    ``Training``. Ethernet-style ``LinkUp`` / ``LinkDown`` / ``NoLink`` map onto
    that set (``NoLink`` becomes ``Down``). Any other string is omitted.
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    lower = v.casefold()
    if lower in ("up", "linkup", "link up", "connected"):
        return "Up"
    if lower in (
        "down",
        "linkdown",
        "link down",
        "disconnected",
        "nolink",
        "no link",
        "no_link",
    ):
        return "Down"
    if lower == "starting":
        return "Starting"
    if lower in ("training", "linknegotiating", "link negotiating", "negotiating"):
        return "Training"
    return None


class BaseNetworkPortNormalizer(ResourceNormalizer):
    """NetworkPort (deprecated). Served only where the BMC has NetworkPorts."""

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": optional("@odata.context"),
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#NetworkPort.v1_4_3.NetworkPort",
            "Id": lambda ctx: _data(ctx, "Id"),
            "Name": lambda ctx: _data(ctx, "Name"),
            "Description": optional("Description"),
            "Status": lambda ctx: _data(ctx, "Status", {}),
            "ActiveLinkTechnology": effective_network_port_active_link_technology,
            "AssociatedNetworkAddresses": lambda ctx: _data(
                ctx, "AssociatedNetworkAddresses"
            ),
            "CurrentLinkSpeedMbps": optional("CurrentLinkSpeedMbps"),
            "EEEEnabled": optional("EEEEnabled"),
            "FlowControlConfiguration": optional("FlowControlConfiguration"),
            "FlowControlStatus": optional("FlowControlStatus"),
            "LinkStatus": omit_if_null(effective_link_status),
            "NetDevFuncMaxBWAlloc": optional("NetDevFuncMaxBWAlloc"),
            "NetDevFuncMinBWAlloc": optional("NetDevFuncMinBWAlloc"),
            "PhysicalPortNumber": optional("PhysicalPortNumber"),
            "PortMaximumMTU": optional("PortMaximumMTU"),
            "SupportedEthernetCapabilities": optional("SupportedEthernetCapabilities"),
            "SupportedLinkCapabilities": optional("SupportedLinkCapabilities"),
            "VendorId": optional("VendorId"),
            "WakeOnLANEnabled": optional("WakeOnLANEnabled"),
            "Oem": lambda ctx: _data(ctx, "Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#NetworkPortCollection.NetworkPortCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#NetworkPortCollection.NetworkPortCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Network Ports",
    "Name": "NetworkPorts Collection",
    "Oem": lambda ctx: _data(ctx, "Oem", {}),
}
