# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell iDRAC FirmwareInventory normalizer."""

from __future__ import annotations

import re
from typing import Any, Dict

from ..base import ResourceNormalizer
from ..types import NormalizationContext
from .base import COLLECTION_MAPPING
from ._shared.firmware_inventory import (
    VendorFirmwareLabels,
    build_sparse_software_inventory,
)


def _dell_updateable(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return value


def dell_firmware_collection_members(members: Any) -> Any:
    """Collection rows that are only an id plus ``Id`` stay idRefs."""
    if not isinstance(members, list):
        return members
    out = []
    for member in members:
        if (
            isinstance(member, dict)
            and isinstance(member.get("@odata.id"), str)
            and member.get("@odata.id")
            and set(member) <= {"@odata.id", "Id"}
        ):
            out.append({"@odata.id": member["@odata.id"]})
        else:
            out.append(member)
    return out


def _dell_collection_members(ctx: NormalizationContext) -> Any:
    members = ctx.data.get("Members")
    if members is None:
        return []
    return dell_firmware_collection_members(members)


DELL_COLLECTION_MAPPING: Dict[str, Any] = {
    **COLLECTION_MAPPING,
    "Members": _dell_collection_members,
}


def parse_dell_inventory_slot(inventory_id: Any) -> str:
    if not isinstance(inventory_id, str):
        return ""
    m = _DELL_SLOT_PREFIX.match(inventory_id.strip())
    if not m:
        return ""
    return m.group(1).lower()


def parse_dell_fqdd_suffix(inventory_id: str) -> Dict[str, str]:
    """Parse Dell FirmwareInventory Id suffix after ``__`` (FQDD) into related_* labels.

    Example: ``Installed-102573-00.3D.67__PSU.Slot.1`` → related_ref=PSU.Slot.1,
    related_kind=power_supply.
    """
    empty = {
        "related_kind": "",
        "related_ref": "",
        "related_scope": "",
        "related_location": "",
    }
    if not isinstance(inventory_id, str) or "__" not in inventory_id:
        return empty
    fqdd = inventory_id.rsplit("__", 1)[-1].strip()
    if not fqdd:
        return empty
    out = dict(empty)
    out["related_ref"] = fqdd
    head = fqdd.split(".", 1)[0].lower()
    kind_map = {
        "psu": (
            "power_supply",
            "Power",
            f"PSU {fqdd.split('.')[-1]}" if "." in fqdd else fqdd,
        ),
        "nic": ("network_adapter", "NIC", fqdd),
        "disk": ("drive", "Disk", fqdd),
        "raid": ("storage", "RAID", fqdd),
        "bios": ("bios", "BIOS", "BIOS"),
        "cpu": ("processor", "CPU", fqdd),
        "dimm": ("memory", "Memory", fqdd),
        "enclosure": ("enclosure", "Enclosure", fqdd),
        "oscollector": ("other", "OSCollector", fqdd),
    }
    if head in kind_map:
        kind, scope, loc = kind_map[head]
        out["related_kind"] = kind
        out["related_scope"] = scope
        out["related_location"] = loc
    else:
        out["related_kind"] = "other"
        out["related_location"] = fqdd
    return out


def _apply_dell_fqdd_from_inventory_id(rp: Dict[str, Any], inventory_id: Any) -> None:
    """Fill related_* from Dell ``__FQDD`` Id suffix when RelatedItem did not."""
    if rp.get("related_ref"):
        return
    if not isinstance(inventory_id, str):
        return
    parsed = parse_dell_fqdd_suffix(inventory_id)
    for key in ("related_kind", "related_ref", "related_scope", "related_location"):
        val = parsed.get(key, "")
        if isinstance(val, str) and val:
            rp[key] = val


def _dell_software_inventory(data: Dict[str, Any]) -> Dict[str, Any]:
    oem = data.get("Oem")
    if not isinstance(oem, dict):
        return {}
    dell = oem.get("Dell")
    if not isinstance(dell, dict):
        return {}
    embedded = dell.get("DellSoftwareInventory")
    if isinstance(embedded, dict):
        return embedded
    return {}


_DELL_SLOT_PREFIX = re.compile(r"^(Installed|Current|Previous)-", re.IGNORECASE)


def _dell_before_related(ctx: NormalizationContext, rp: Dict[str, Any]) -> None:
    """Dell slot, installation date and component id, from the Id and DellSoftwareInventory."""
    slot = parse_dell_inventory_slot(ctx.data.get("Id"))
    if slot:
        rp["inventory_slot"] = slot
    dell_sw = _dell_software_inventory(ctx.data)
    inst = dell_sw.get("InstallationDate")
    if isinstance(inst, str) and inst.strip():
        rp["installation_date"] = inst.strip()
    comp_id = dell_sw.get("ComponentID")
    if comp_id is not None and comp_id != "":
        rp["component_id"] = str(comp_id)


def _dell_without_related(ctx: NormalizationContext, rp: Dict[str, Any]) -> None:
    _apply_dell_fqdd_from_inventory_id(rp, ctx.data.get("Id"))


DELL_FIRMWARE_LABELS = VendorFirmwareLabels(
    before_related=_dell_before_related,
    without_related=_dell_without_related,
)


class DellFirmwareInventoryNormalizer(ResourceNormalizer):
    """Dell FirmwareInventory → SoftwareInventory v1_10_2."""

    def normalized_body_from_prefetch(self, ctx: NormalizationContext):
        body = build_sparse_software_inventory(ctx, DELL_FIRMWARE_LABELS)
        if "Updateable" in body:
            body["Updateable"] = _dell_updateable(body["Updateable"])
        return body

    def field_map(self) -> Dict[str, Any]:
        return {}
