# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base PCIeDevice normalizer."""

from __future__ import annotations

from typing import Any, Dict, Optional

from redpool.redfish_client import redfish_get_json

from ...base import ResourceNormalizer
from ...optional import OMIT, optional
from ...pcie_display import coalesce_pcie_device_model, prefer_pcie_device_product_model
from ...types import NormalizationContext
from ...vendor_id import normalize_vendor_id


def _chassis_pcie_device_model(ctx: NormalizationContext) -> Any:
    chosen = prefer_pcie_device_product_model(
        ctx.data.get("Model"), ctx.data.get("Name"), ctx.data.get("PartNumber")
    )
    if chosen is not None:
        return chosen
    return coalesce_pcie_device_model(
        ctx.data.get("Model"), ctx.data.get("Name"), ctx.data.get("Description")
    )


# ------------------------------------------------------------------
# PCIeSlots join: collectors read only ``Slot.Location.Info`` or
# ``Slot.Location.PartLocation.ServiceLabel`` for the device's placement
# label. Some vendors (e.g. Dell) embed ``Slot.Lanes``/``PCIeType`` and a
# bare ``LocationOrdinalValue`` on the device but never a usable label, so
# the collector location ends up empty. When that label is missing, look
# up the sibling chassis ``PCIeSlots`` resource and match this device via
# ``Slots[].Links.PCIeDevice`` to fill in a label (preferring the vendor
# OEM slot name, e.g. Dell ``SlotKey``). No-op for vendors that already
# have a usable label (e.g. Lenovo) or whose ``PCIeSlots`` has no
# back-reference to devices (e.g. HPE).
# ------------------------------------------------------------------

_PCIE_SLOT_PREFETCH_KEY = "matched_pcie_slot"


def _slot_part_location(data: Dict[str, Any]) -> Dict[str, Any]:
    slot = data.get("Slot")
    loc = slot.get("Location") if isinstance(slot, dict) else None
    part = loc.get("PartLocation") if isinstance(loc, dict) else None
    return part if isinstance(part, dict) else {}


def _device_has_slot_label(data: Dict[str, Any]) -> bool:
    """True when the collector can already derive a non-empty location string."""
    slot = data.get("Slot")
    loc = slot.get("Location") if isinstance(slot, dict) else None
    if not isinstance(loc, dict):
        return False
    if isinstance(loc.get("Info"), str) and loc["Info"].strip():
        return True
    label = _slot_part_location(data).get("ServiceLabel")
    return isinstance(label, str) and bool(label.strip())


def _chassis_root_from_device_odata_id(odata_id: str) -> Optional[str]:
    marker = "/PCIeDevices/"
    if marker not in odata_id:
        return None
    root = odata_id.split(marker, 1)[0].split("#", 1)[0]
    return root or None


def _pcie_interface_incomplete(data: Dict[str, Any]) -> bool:
    """True when PCIeInterface lacks gen/lanes useful for collector labels."""
    iface = data.get("PCIeInterface")
    if not isinstance(iface, dict) or not iface:
        return True
    has_type = bool(
        (isinstance(iface.get("PCIeType"), str) and iface["PCIeType"].strip())
        or (isinstance(iface.get("MaxPCIeType"), str) and iface["MaxPCIeType"].strip())
    )
    lanes = iface.get("LanesInUse")
    max_lanes = iface.get("MaxLanes")
    has_lanes = (isinstance(lanes, (int, float)) and lanes > 0) or (
        isinstance(max_lanes, (int, float)) and max_lanes > 0
    )
    return not (has_type and has_lanes)


def prefetch_pcie_device_slot(ctx: NormalizationContext) -> None:
    """Load the sibling ``PCIeSlots`` entry that links back to this device.

    Prefetch when the slot location label is missing *or* PCIeInterface gen/lanes
    are empty so we can fill both from the matched slot.
    """
    ctx.prefetched.pop(_PCIE_SLOT_PREFETCH_KEY, None)
    if ctx.client is None:
        return
    need_label = not _device_has_slot_label(ctx.data)
    need_iface = _pcie_interface_incomplete(ctx.data)
    if not need_label and not need_iface:
        return
    chassis_root = _chassis_root_from_device_odata_id(ctx.odata_id)
    if not chassis_root:
        return
    slots_doc = redfish_get_json(ctx.client, f"{chassis_root}/PCIeSlots")
    slots = slots_doc.get("Slots") if isinstance(slots_doc, dict) else None
    if not isinstance(slots, list):
        return
    target = (ctx.odata_id or "").split("#", 1)[0].rstrip("/")
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        links = slot.get("Links")
        refs = links.get("PCIeDevice") if isinstance(links, dict) else None
        if not isinstance(refs, list):
            continue
        for ref in refs:
            oid = ref.get("@odata.id") if isinstance(ref, dict) else None
            if isinstance(oid, str) and oid.split("#", 1)[0].rstrip("/") == target:
                ctx.prefetched[_PCIE_SLOT_PREFETCH_KEY] = slot
                return


def _matched_slot_label(
    matched: Dict[str, Any], own_part_location: Dict[str, Any]
) -> Optional[str]:
    """Prefer vendor OEM slot name (e.g. Dell ``SlotKey``), then the slot's own label/ordinal."""
    oem = matched.get("Oem")
    if isinstance(oem, dict):
        for vendor_block in oem.values():
            if isinstance(vendor_block, dict):
                key = vendor_block.get("SlotKey")
                if isinstance(key, str) and key.strip():
                    return key.strip()
    loc = matched.get("Location")
    if isinstance(loc, dict):
        info = loc.get("Info")
        if isinstance(info, str) and info.strip():
            return info.strip()
        part = loc.get("PartLocation")
        if isinstance(part, dict):
            label = part.get("ServiceLabel")
            if isinstance(label, str) and label.strip():
                return label.strip()
    ordinal = own_part_location.get("LocationOrdinalValue")
    if ordinal is not None:
        return f"Slot {ordinal}"
    return None


def _effective_slot(ctx: NormalizationContext) -> Any:
    """Return the device's own ``Slot``, with a location label filled in from ``PCIeSlots`` if missing."""
    own = ctx.data.get("Slot")
    own = dict(own) if isinstance(own, dict) else {}
    if _device_has_slot_label(ctx.data):
        return own

    matched = ctx.prefetched.get(_PCIE_SLOT_PREFETCH_KEY)
    if not isinstance(matched, dict):
        return own

    own_part_location = dict(_slot_part_location(ctx.data))
    label = _matched_slot_label(matched, own_part_location)
    if not label:
        return own

    own_part_location["ServiceLabel"] = label
    own_location = (
        dict(own.get("Location")) if isinstance(own.get("Location"), dict) else {}
    )
    own_location["PartLocation"] = own_part_location
    own["Location"] = own_location
    return own


def _effective_pcie_interface(ctx: NormalizationContext) -> Any:
    """Fill empty PCIeInterface gen/lanes from the matched PCIeSlots entry."""
    own = ctx.data.get("PCIeInterface")
    own = dict(own) if isinstance(own, dict) else {}
    if not _pcie_interface_incomplete(ctx.data):
        return own

    matched = ctx.prefetched.get(_PCIE_SLOT_PREFETCH_KEY)
    if not isinstance(matched, dict):
        return own

    # Slot-level fields: PCIeType / Lanes (Dell PCIeSlots)
    slot_type = matched.get("PCIeType")
    if isinstance(slot_type, str) and slot_type.strip():
        if not (isinstance(own.get("PCIeType"), str) and own["PCIeType"].strip()):
            own["PCIeType"] = slot_type.strip()
        if not (isinstance(own.get("MaxPCIeType"), str) and own["MaxPCIeType"].strip()):
            own["MaxPCIeType"] = slot_type.strip()
    lanes = matched.get("Lanes")
    if isinstance(lanes, (int, float)) and lanes > 0:
        if not (
            isinstance(own.get("LanesInUse"), (int, float)) and own["LanesInUse"] > 0
        ):
            own["LanesInUse"] = int(lanes)
        if not (isinstance(own.get("MaxLanes"), (int, float)) and own["MaxLanes"] > 0):
            own["MaxLanes"] = int(lanes)
    return own


class BasePCIeDeviceNormalizer(ResourceNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_pcie_device_slot(ctx)

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#PCIeDevice.PCIeDevice",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#PCIeDevice.v1_14_0.PCIeDevice",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "DeviceType": optional("DeviceType"),
            "Manufacturer": lambda ctx: normalize_vendor_id(
                ctx.data.get("Manufacturer")
            ),
            "Model": _chassis_pcie_device_model,
            "SerialNumber": optional("SerialNumber"),
            "PartNumber": optional("PartNumber"),
            "SKU": optional("SKU"),
            "FirmwareVersion": optional("FirmwareVersion"),
            "PCIeInterface": _effective_pcie_interface,
            "PCIeFunctions": lambda ctx: ctx.data.get("PCIeFunctions", {}),
            "Slot": _effective_slot,
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


def linked_pcie_device_members(ctx: NormalizationContext) -> Any:
    """Keep members that already have an ``@odata.id``.

    HPE lists Chassis PCIeDevices with an ``Id`` and a blank link. Those URIs
    are ``ResourceMissingAtURI``, not devices. A real device keeps its link
    whether or not the port is up.
    """
    members = ctx.data.get("Members")
    if members is None:
        return []
    if not isinstance(members, list):
        return members
    linked = []
    for member in members:
        if not isinstance(member, dict):
            linked.append(member)
            continue
        oid = member.get("@odata.id")
        if isinstance(oid, str) and oid.strip():
            linked.append(member)
    return linked


def linked_pcie_device_member_count(ctx: NormalizationContext) -> Any:
    members = linked_pcie_device_members(ctx)
    if members is OMIT:
        return OMIT
    if isinstance(members, list):
        return len(members)
    return ctx.data.get("Members@odata.count")


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#PCIeDeviceCollection.PCIeDeviceCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#PCIeDeviceCollection.PCIeDeviceCollection",
    "Members": linked_pcie_device_members,
    "Members@odata.count": linked_pcie_device_member_count,
    "Description": "Collection of PCIe Devices",
    "Name": "PCIeDeviceCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
