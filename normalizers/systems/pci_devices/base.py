# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base PCIeDevice normalizer for devices under Systems.

Passes the standard Redfish ``PCIeDevice`` fields through unchanged (same as the
chassis variant), rewriting ``@odata.id`` from ``PCIDevices`` → ``PCIeDevices``.
HPE's ``HpeServerPciDevice`` conversion lives in ``hpe.py``.
"""

from __future__ import annotations

import copy
from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import omit_if_null, optional
from ...pcie_display import coalesce_pcie_device_model
from ...types import NormalizationContext
from ...url_rewrites import rewrite_odata_id
from ...vendor_id import normalize_vendor_id

# PCI base-class code → Redfish DeviceClass string (shared by vendors)
_CLASS_CODE_MAP: Dict[int, str] = {
    0: "UnclassifiedDevice",
    1: "MassStorageController",
    2: "NetworkController",
    3: "DisplayController",
    4: "MultimediaController",
    5: "MemoryController",
    6: "Bridge",
    7: "CommunicationController",
    8: "GenericSystemPeripheral",
    9: "InputDeviceController",
    10: "DockingStation",
    11: "Processor",
    12: "SerialBusController",
    13: "WirelessController",
    14: "IntelligentController",
    15: "SatelliteCommunicationsController",
    16: "EncryptionController",
    17: "SignalProcessingController",
    18: "ProcessingAccelerators",
    19: "NonEssentialInstrumentation",
    64: "Coprocessor",
    255: "UnassignedClass",
}


def device_class_from_pci_class(class_code: Any) -> str | None:
    """Map integer PCI base class code to Redfish DeviceClass enum."""
    if isinstance(class_code, int):
        return _CLASS_CODE_MAP.get(class_code, "Other")
    return None


def _normalize_odata_id(ctx: NormalizationContext) -> str:
    return rewrite_odata_id(ctx.odata_id)


def _device_type(ctx: NormalizationContext) -> str | None:
    return ctx.data.get("DeviceType")


def _manufacturer(ctx: NormalizationContext) -> str | None:
    return ctx.data.get("Manufacturer")


def pcie_interface(ctx: NormalizationContext) -> Dict[str, Any]:
    return ctx.data.get("PCIeInterface", {})


def pcie_functions_link(ctx: NormalizationContext) -> Dict[str, Any]:
    return ctx.data.get("PCIeFunctions", {})


def pci_device_status(ctx: NormalizationContext) -> Dict[str, Any]:
    return ctx.data.get("Status", {})


def pci_device_links(ctx: NormalizationContext) -> Dict[str, Any]:
    return ctx.data.get("Links", {})


def pci_device_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    """Pass vendor ``Oem`` through."""
    src = ctx.data.get("Oem")
    return copy.deepcopy(src) if isinstance(src, dict) else {}


class BaseSystemsPCIeDeviceNormalizer(ResourceNormalizer):
    """Normalizes a standard PCIeDevice."""

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#PCIeDevice.PCIeDevice",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": _normalize_odata_id,
            "@odata.type": "#PCIeDevice.v1_14_0.PCIeDevice",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": omit_if_null(
                lambda ctx: ctx.data.get("Description") or ctx.data.get("Name")
            ),
            "DeviceType": omit_if_null(_device_type),
            "Manufacturer": lambda ctx: normalize_vendor_id(_manufacturer(ctx)),
            "Model": lambda ctx: coalesce_pcie_device_model(
                ctx.data.get("Model"),
                ctx.data.get("Name"),
                ctx.data.get("Description"),
            ),
            "SerialNumber": optional("SerialNumber"),
            "PartNumber": optional("PartNumber"),
            "SKU": optional("SKU"),
            "FirmwareVersion": optional("FirmwareVersion"),
            "PCIeInterface": pcie_interface,
            "PCIeFunctions": pcie_functions_link,
            "Slot": lambda ctx: ctx.data.get("Slot", {}),
            "Status": pci_device_status,
            "Links": pci_device_links,
            "Assembly": lambda ctx: ctx.data.get("Assembly", {}),
            "Oem": pci_device_oem,
        }


def _collection_members(ctx: NormalizationContext) -> list[Dict[str, Any]] | Any:
    """Drop members whose ``@odata.id`` is blank, then rewrite the links that remain."""
    members = ctx.data.get("Members")
    if members is None:
        return None
    if not isinstance(members, list):
        return members
    linked: list[Dict[str, Any]] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        oid = member.get("@odata.id")
        if not isinstance(oid, str) or not oid.strip():
            continue
        kept = copy.deepcopy(member)
        kept["@odata.id"] = rewrite_odata_id(oid)
        linked.append(kept)
    return linked


def _collection_member_count(ctx: NormalizationContext) -> Any:
    members = _collection_members(ctx)
    if isinstance(members, list):
        return len(members)
    return optional("Members@odata.count")(ctx)


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#PCIeDeviceCollection.PCIeDeviceCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": _normalize_odata_id,
    "@odata.type": "#PCIeDeviceCollection.PCIeDeviceCollection",
    "Members": _collection_members,
    "Members@odata.count": _collection_member_count,
    "Description": "Collection of PCIe Devices",
    "Name": "PCIeDeviceCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
