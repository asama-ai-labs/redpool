# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Shared helpers for UpdateService FirmwareInventory normalization."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ..._shared.redfish_dates import date_time_or_none
from ...types import NormalizationContext

_INVALID_RELEASE_DATES = frozenset({"00:00:00Z", "00:00:00z"})


@dataclass(frozen=True)
class VendorFirmwareLabels:
    """Vendor-specific labels for one FirmwareInventory document.

    ``before_related`` adds labels ahead of the RelatedItem labels. ``without_related``
    runs only when the document has no RelatedItem, to fill labels from its Id instead.
    """

    before_related: Optional[Callable[[NormalizationContext, Dict[str, Any]], None]] = (
        None
    )
    without_related: Optional[
        Callable[[NormalizationContext, Dict[str, Any]], None]
    ] = None


NO_VENDOR_LABELS = VendorFirmwareLabels()


_REDFISH_PREFIX = "/redfish/v1/"

_DRIVE_M2_BAY = re.compile(r"^Drive\.M\.2_Bay_(\d+)$", re.IGNORECASE)
_DRIVE_BAY = re.compile(r"^Drive\.Bay_(\d+)$", re.IGNORECASE)


def normalize_release_date(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or s in _INVALID_RELEASE_DATES:
        return None
    return date_time_or_none(s)


def _first_related_item_uri(data: Dict[str, Any]) -> str:
    related = data.get("RelatedItem")
    if not isinstance(related, list) or not related:
        return ""
    first = related[0]
    if isinstance(first, dict):
        uri = first.get("@odata.id")
        return uri if isinstance(uri, str) else ""
    return ""


def _drive_location_from_ref(ref: str, scope: str) -> str:
    m = _DRIVE_M2_BAY.match(ref)
    if m:
        return f"M.2 - Drive{m.group(1)}"
    m = _DRIVE_BAY.match(ref)
    if m:
        return f"Drive {m.group(1)}"
    if ref.isdigit():
        return f"Drive {ref}"
    if scope:
        return f"{scope} {ref}"
    return ref


def _path_segments(uri: str) -> tuple[List[str], str]:
    """Return Redfish path segments (no /redfish/v1) and optional # fragment path."""
    base = uri.strip()
    fragment = ""
    if "#" in base:
        base, fragment = base.split("#", 1)
        fragment = fragment.strip("/")
    if base.startswith(_REDFISH_PREFIX):
        base = base[len(_REDFISH_PREFIX) :]
    elif base.startswith("/redfish/v1"):
        base = base[len("/redfish/v1") :].lstrip("/")
    segments = [s for s in base.strip("/").split("/") if s]
    return segments, fragment


def parse_related_item_uri(uri: str) -> Dict[str, str]:
    """Parse RelatedItem @odata.id into related_kind/ref/scope/location labels."""
    empty = {
        "related_kind": "",
        "related_ref": "",
        "related_scope": "",
        "related_location": "",
    }
    if not isinstance(uri, str) or not uri.strip():
        return empty

    segments, fragment = _path_segments(uri.strip())
    if not segments and not fragment:
        return empty

    out = dict(empty)
    frag_parts = [s for s in fragment.split("/") if s] if fragment else []
    if "PowerSupplies" in frag_parts:
        idx = frag_parts.index("PowerSupplies")
        psu_index = frag_parts[idx + 1] if idx + 1 < len(frag_parts) else ""
        out["related_kind"] = "power_supply"
        out["related_ref"] = psu_index
        out["related_scope"] = "Power"
        if psu_index.isdigit():
            out["related_location"] = f"PSU {int(psu_index) + 1}"
        elif psu_index:
            out["related_location"] = f"PSU {psu_index}"
        return out

    if not segments:
        return empty

    ref = segments[-1]
    path_joined = "/".join(segments)
    lowered = path_joined.lower()
    lower_segments = [s.lower() for s in segments]

    if "drives" in lowered:
        drive_idx = next(i for i, s in enumerate(lower_segments) if s == "drives")
        out["related_kind"] = "drive"
        out["related_ref"] = (
            segments[drive_idx + 1] if drive_idx + 1 < len(segments) else ref
        )
        if drive_idx >= 1:
            out["related_scope"] = segments[drive_idx - 1]
        out["related_location"] = _drive_location_from_ref(
            out["related_ref"], out["related_scope"]
        )
        return out

    if "pciedevices" in lowered:
        out["related_kind"] = "pcie"
        out["related_ref"] = ref
        out["related_location"] = f"PCIe {ref}"
        return out

    if "networkadapters" in lowered:
        out["related_kind"] = "network_adapter"
        out["related_ref"] = ref
        out["related_location"] = f"Network {ref}"
        return out

    if "processors" in lowered:
        out["related_kind"] = "processor"
        out["related_ref"] = ref
        out["related_location"] = (
            ref if ref.upper().startswith("GPU") else f"Processor {ref}"
        )
        return out

    if "managers" in lowered:
        out["related_kind"] = "manager"
        out["related_ref"] = ref
        out["related_location"] = "BMC"
        return out

    if ref.lower() == "bios" or path_joined.endswith("/Bios"):
        out["related_kind"] = "bios"
        out["related_ref"] = "Bios"
        out["related_location"] = "BIOS"
        return out

    if "storage" in lowered:
        storage_idx = next(i for i, s in enumerate(lower_segments) if s == "storage")
        pool = segments[storage_idx + 1] if storage_idx + 1 < len(segments) else ref
        out["related_kind"] = "storage"
        out["related_ref"] = pool
        out["related_scope"] = pool
        out["related_location"] = pool
        return out

    if "power" in lowered:
        out["related_kind"] = "power"
        out["related_ref"] = ref
        out["related_location"] = "Power"
        return out

    if lower_segments[0] == "systems" and len(lower_segments) == 2:
        out["related_kind"] = "system"
        out["related_ref"] = ref
        out["related_location"] = "System"
        return out

    out["related_kind"] = "other"
    out["related_ref"] = ref
    out["related_location"] = ref
    return out


def _apply_related_item_labels(rp: Dict[str, Any], uri: str) -> None:
    rp["related_item_uri"] = uri
    parsed = parse_related_item_uri(uri)
    for key in ("related_kind", "related_ref", "related_scope", "related_location"):
        val = parsed.get(key, "")
        if isinstance(val, str) and val:
            rp[key] = val


def _sparse_status(status: Any) -> Dict[str, Any]:
    if not isinstance(status, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in ("Health", "State", "HealthRollup"):
        val = status.get(key)
        if val is not None and val != "":
            out[key] = val
    return out


def _omit_empty_value(val: Any) -> bool:
    if val is None:
        return True
    if isinstance(val, str) and not val.strip():
        return True
    if isinstance(val, (list, dict)) and len(val) == 0:
        return True
    return False


def build_redpool_firmware_inventory(
    ctx: NormalizationContext, vendor: VendorFirmwareLabels = NO_VENDOR_LABELS
) -> Dict[str, Any]:
    data = ctx.data
    rp: Dict[str, Any] = {}

    inv_id = data.get("Id")
    if isinstance(inv_id, str) and inv_id:
        rp["inventory_id"] = inv_id

    if vendor.before_related is not None:
        vendor.before_related(ctx, rp)

    related = _first_related_item_uri(data)
    if related:
        _apply_related_item_labels(rp, related)
    elif vendor.without_related is not None:
        vendor.without_related(ctx, rp)

    return rp


def merge_firmware_inventory_oem(
    ctx: NormalizationContext, vendor: VendorFirmwareLabels = NO_VENDOR_LABELS
) -> Dict[str, Any]:
    """Preserve vendor Oem and attach Oem.Redpool.FirmwareInventory."""
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    rp_root: Dict[str, Any] = {}
    existing = out.get("Redpool")
    if isinstance(existing, dict):
        rp_root = copy.deepcopy(existing)

    fi = build_redpool_firmware_inventory(ctx, vendor)
    if fi:
        rp_root["FirmwareInventory"] = fi
    elif "FirmwareInventory" in rp_root:
        rp_root.pop("FirmwareInventory", None)

    if rp_root:
        out["Redpool"] = rp_root
    else:
        out.pop("Redpool", None)
    return out


def build_sparse_software_inventory(
    ctx: NormalizationContext, vendor: VendorFirmwareLabels = NO_VENDOR_LABELS
) -> Dict[str, Any]:
    """Build normalized SoftwareInventory v1_10_2 body; omit absent keys."""
    data = ctx.data
    body: Dict[str, Any] = {
        "@odata.context": "/redfish/v1/$metadata#SoftwareInventory.SoftwareInventory",
        "@odata.type": "#SoftwareInventory.v1_10_2.SoftwareInventory",
        "@odata.id": ctx.odata_id,
    }

    etag = data.get("@odata.etag")
    if not _omit_empty_value(etag):
        body["@odata.etag"] = etag

    for key in (
        "Id",
        "Name",
        "Description",
        "Version",
        "VersionString",
        "SoftwareId",
        "Manufacturer",
        "Updateable",
        "WriteProtected",
        "LowestSupportedVersion",
        "RelatedItem@odata.count",
    ):
        val = data.get(key)
        if not _omit_empty_value(val):
            body[key] = val

    release = normalize_release_date(data.get("ReleaseDate"))
    if release:
        body["ReleaseDate"] = release

    status = _sparse_status(data.get("Status"))
    if status:
        body["Status"] = status

    related = data.get("RelatedItem")
    if isinstance(related, list) and related:
        body["RelatedItem"] = related

    uefi = data.get("UefiDevicePaths")
    if isinstance(uefi, list) and uefi:
        body["UefiDevicePaths"] = uefi

    actions = data.get("Actions")
    if isinstance(actions, dict) and actions:
        body["Actions"] = actions

    oem = merge_firmware_inventory_oem(ctx, vendor)
    if oem:
        body["Oem"] = oem

    return body
