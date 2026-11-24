# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE-specific PCIeDevice normalizer.

- Derives Slot from LocationString or StructuredName when HPE does not expose
  a standard Slot property.
- Uses pci.ids to derive human-readable vendor/device names when Manufacturer
  or Model are missing.
- Registers a request rewrite so Systems/{id}/PCIeDevices is served from
  Chassis/{id}/PCIeDevices (HPE exposes PCIeDevices and PCIeFunctions under Chassis).
- Merges Chassis PCIeDevice (Manufacturer, Model, Status, etc.) with
  Systems/PCIDevices (LocationString, StructuredName, bus/location) for a full
  Redfish PCIeDevice response.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from redpool import pci_ids
from redpool.redfish_client import redfish_get_json

from ..._shared.system_chassis import begin_system_chassis_memo, chassis_for_system
from ...evaluator import evaluate
from ...optional import omit_if_null
from ...pci_class_code import normalize_pci_class_code, pci_id_to_int
from ...pcie_display import coalesce_pcie_device_model, prefer_pcie_device_product_model
from ...apply import normalize_resource
from ...request_rewrites import (
    RequestRewriteRule,
    RewriteCall,
    register_request_rewrite,
)
from ...types import NormalizationContext
from ...url_rewrites import rewrite_odata_id
from ...vendor_id import normalize_vendor_id
from .base import (
    COLLECTION_MAPPING,
    BaseSystemsPCIeDeviceNormalizer,
    pci_device_oem,
    pci_device_links,
    pcie_functions_link,
    pcie_interface,
    pci_device_status,
)
from .pcie_functions.base import (
    COLLECTION_MAPPING as PCIE_FUNCTION_COLLECTION_MAPPING,
    BaseSystemsPCIeFunctionNormalizer,
)

_log = logging.getLogger(__name__)

_PCIE_DEVICE_TYPES = frozenset({"SingleFunction", "MultiFunction", "Simulated"})

# Fields to merge from Systems/PCIDevices (HpeServerPciDevice) into Chassis PCIeDevice
# so the response satisfies Redfish PCIeDevice and our Slot derivation.
_SYSTEMS_PCI_FIELDS_TO_MERGE = (
    "LocationString",
    "StructuredName",
    "BusNumber",
    "SegmentNumber",
    "DeviceNumber",
    "FunctionNumber",
    "ClassCode",
    "SubclassCode",
    "DeviceLocation",
    "DeviceType",
    "UEFIDevicePath",
    "Bifurcated",
    "DeviceInstance",
    "DeviceSubInstance",
    "VendorID",
    "DeviceID",
    "SubsystemVendorID",
    "SubsystemDeviceID",
)


def _pci_id_lookup_hex(val: Any) -> Optional[str]:
    """Format a PCI id for pci.ids lookup (lowercase 4 hex chars)."""
    n = pci_id_to_int(val)
    return None if n is None else f"{n:04x}"


# -----------------------------------------------------------------------------
# Slot derivation (normalizer)
# -----------------------------------------------------------------------------


def _slot_from_hpe(ctx: NormalizationContext) -> Dict[str, Any]:
    """Derive Slot from HPE LocationString and/or StructuredName.

    When both are present: Info = LocationString (human-readable),
    ServiceLabel = StructuredName (structured identifier). Otherwise use
    whichever is available for both fields.
    """
    location_string = ctx.data.get("LocationString")
    structured = ctx.data.get("StructuredName")
    has_loc = isinstance(location_string, str) and location_string.strip()
    has_struct = isinstance(structured, str) and structured.strip()

    if has_loc:
        info = location_string
        service_label = structured if has_struct else location_string
        return {
            "Location": {
                "Info": info,
                "PartLocation": {
                    "ServiceLabel": service_label,
                    "LocationType": "Slot",
                },
            },
        }
    if has_struct:
        return {
            "Location": {
                "Info": structured,
                "PartLocation": {
                    "ServiceLabel": structured.replace(".", " "),
                    "LocationType": "Slot",
                },
            },
        }
    return {}


def _effective_hpe_slot(ctx: NormalizationContext) -> Dict[str, Any]:
    """Use a Systems-derived slot when one exists. Otherwise keep the Chassis slot."""
    derived = _slot_from_hpe(ctx)
    if derived:
        return derived
    slot = ctx.data.get("Slot")
    if isinstance(slot, dict) and slot:
        return slot
    return {}


def _is_hpe_pci_device(ctx: NormalizationContext) -> bool:
    """True for an iLO ``HpeServerPciDevice`` payload. HPE also serves standard PCIeDevices."""
    return "HpeServerPciDevice" in ctx.odata_type


def _hpe_pcie_interface(ctx: NormalizationContext) -> Dict[str, Any]:
    return {} if _is_hpe_pci_device(ctx) else pcie_interface(ctx)


def _hpe_pcie_functions_link(ctx: NormalizationContext) -> Dict[str, Any]:
    if _is_hpe_pci_device(ctx):
        return {"@odata.id": f"{rewrite_odata_id(ctx.odata_id)}/PCIeFunctions"}
    return pcie_functions_link(ctx)


def _hpe_status(ctx: NormalizationContext) -> Dict[str, Any]:
    if _is_hpe_pci_device(ctx):
        # HpeServerPciDevice does not expose Status; per Redfish DSP0266,
        # use null when value is unknown (schema allows null for State and Health).
        return {"State": None, "Health": None}
    return pci_device_status(ctx)


def _hpe_links(ctx: NormalizationContext) -> Dict[str, Any]:
    return {} if _is_hpe_pci_device(ctx) else pci_device_links(ctx)


def _hpe_oem_dict(ctx: NormalizationContext) -> Dict[str, Any]:
    """Return Oem.Hpe dict when present (HPE PCI fields may live here)."""
    oem = ctx.data.get("Oem")
    if not isinstance(oem, dict):
        return {}
    hpe = oem.get("Hpe")
    return hpe if isinstance(hpe, dict) else {}


def _hpe_device_type(ctx: NormalizationContext) -> str | None:
    """Redfish DeviceType is SingleFunction, MultiFunction, or Simulated.

    iLO ``HpeServerPciDevice.DeviceType`` is a location label such as
    ``Flexible LOM``. Keep a real enum value. The label is not a PCIeDevice property.
    """
    raw = ctx.data.get("DeviceType")
    if raw in _PCIE_DEVICE_TYPES:
        return raw
    # A single HPE device does not say how many functions it has, so DeviceType is
    # omitted rather than guessed as SingleFunction.
    return None


def _pci_field(ctx: NormalizationContext, key: str) -> Any:
    """Resolve a PCI id field from top-level or Oem.Hpe."""
    v = ctx.data.get(key)
    if v is not None and v != "":
        return v
    return _hpe_oem_dict(ctx).get(key)


class HpeSystemsPCIeDeviceNormalizer(BaseSystemsPCIeDeviceNormalizer):
    """PCIeDevice normalizer for HPE.

    - Derives Slot from LocationString or StructuredName.
    - Fills in Manufacturer and Model from pci.ids when missing.
    """

    def field_map(self) -> Dict[str, Any]:
        fm = super().field_map()

        def _manufacturer_raw(ctx: NormalizationContext) -> Any:
            if ctx.data.get("Manufacturer"):
                return ctx.data.get("Manufacturer")
            vid = _pci_id_lookup_hex(_pci_field(ctx, "VendorID"))
            name, _, _ = pci_ids.lookup_pci_names(vid)
            return name

        def _model(ctx: NormalizationContext) -> Any:
            chosen = prefer_pcie_device_product_model(
                ctx.data.get("Model"),
                ctx.data.get("Name"),
                ctx.data.get("PartNumber"),
            )
            if chosen is not None:
                return chosen
            if ctx.data.get("Model"):
                return ctx.data.get("Model")
            vid = _pci_id_lookup_hex(_pci_field(ctx, "VendorID"))
            did = _pci_id_lookup_hex(_pci_field(ctx, "DeviceID"))
            svid = _pci_id_lookup_hex(_pci_field(ctx, "SubsystemVendorID"))
            sdid = _pci_id_lookup_hex(_pci_field(ctx, "SubsystemDeviceID"))
            _, dev_name, subsys_name = pci_ids.lookup_pci_names(vid, did, svid, sdid)
            inferred = subsys_name or dev_name
            if inferred:
                return inferred
            return coalesce_pcie_device_model(
                ctx.data.get("Model"),
                ctx.data.get("Name"),
                ctx.data.get("Description"),
            )

        return {
            **fm,
            "DeviceType": omit_if_null(_hpe_device_type),
            "Slot": _effective_hpe_slot,
            "Manufacturer": lambda ctx: normalize_vendor_id(_manufacturer_raw(ctx)),
            "Model": _model,
            "PCIeInterface": _hpe_pcie_interface,
            "PCIeFunctions": _hpe_pcie_functions_link,
            "Status": _hpe_status,
            "Links": _hpe_links,
            "Oem": pci_device_oem,
        }


# -----------------------------------------------------------------------------
# Merge Chassis PCIeDevice + Systems/PCIDevices for full Redfish response
# -----------------------------------------------------------------------------


def _get_chassis_pci_ids(
    client: Any, chassis_device_path: str, chassis_body: Dict[str, Any]
) -> Optional[tuple[int, int, int, int]]:
    """Get (VendorID, DeviceID, SubsystemVendorID, SubsystemDeviceID) from Chassis device or its first PCIeFunction."""
    # Some Chassis PCIeDevice resources expose PCI ids directly (varying casing)
    for vid_key in ("VendorID", "VendorId"):
        vid = pci_id_to_int(chassis_body.get(vid_key))
        if vid is not None:
            did = pci_id_to_int(
                chassis_body.get("DeviceID") or chassis_body.get("DeviceId")
            )
            svid = pci_id_to_int(
                chassis_body.get("SubsystemVendorID")
                or chassis_body.get("SubsystemVendorId")
            )
            sdid = pci_id_to_int(
                chassis_body.get("SubsystemDeviceID")
                or chassis_body.get("SubsystemDeviceId")
            )
            if did is not None:
                return (vid, did, svid or 0, sdid or 0)
    # Otherwise read from first PCIeFunction
    try:
        func_coll_path = chassis_device_path.rstrip("/") + "/PCIeFunctions"
        func_coll = redfish_get_json(client, func_coll_path)
        members = func_coll.get("Members") or []
        if not members or not isinstance(members[0], dict):
            return None
        func_url = (members[0].get("@odata.id") or "").strip()
        if not func_url or not func_url.startswith("/"):
            return None
        func_path = func_url.split("?", 1)[0]
        func_body = redfish_get_json(client, func_path)
        vid = pci_id_to_int(func_body.get("VendorId") or func_body.get("VendorID"))
        did = pci_id_to_int(func_body.get("DeviceId") or func_body.get("DeviceID"))
        svid = pci_id_to_int(
            func_body.get("SubsystemVendorId") or func_body.get("SubsystemVendorID")
        )
        sdid = pci_id_to_int(
            func_body.get("SubsystemId") or func_body.get("SubsystemDeviceID")
        )
        if vid is not None and did is not None:
            return (vid, did, svid or 0, sdid or 0)
    except Exception:
        pass
    return None


def _norm_path(url: Any) -> str:
    return str(url or "").split("?", 1)[0].strip().rstrip("/")


def _usable_serial(serial: Any) -> str | None:
    if not isinstance(serial, str):
        return None
    text = serial.strip()
    if not text or text.upper().startswith("DUMMY-"):
        return None
    return text


def _candidate_from_devices(
    client: Any,
    chassis_device_path: str,
    chassis_body: Dict[str, Any],
    candidates: list[tuple[str, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Pick the candidate whose Chassis HpeServerDevice shares the chassis serial.

    Returns None unless the serial is real and exactly one candidate's Device
    carries it.
    """
    serial = _usable_serial(chassis_body.get("SerialNumber"))
    m = re.match(r"(.*?/Chassis/[^/]+)/", chassis_device_path)
    if serial is None or m is None:
        return None
    by_path = {_norm_path(path): body for path, body in candidates}
    matches: list[Dict[str, Any]] = []
    try:
        coll = redfish_get_json(client, m.group(1) + "/Devices")
        for member in coll.get("Members") or []:
            url = (
                _norm_path(member.get("@odata.id")) if isinstance(member, dict) else ""
            )
            if not url:
                continue
            device = redfish_get_json(client, url)
            if _usable_serial(device.get("SerialNumber")) != serial:
                continue
            instances = device.get("DeviceInstances") or []
            if not instances or not isinstance(instances[0], dict):
                continue
            target = by_path.get(_norm_path(instances[0].get("@odata.id")))
            if target is not None:
                matches.append(target)
    except Exception:
        return None
    return matches[0] if len(matches) == 1 else None


def _same_location(candidates: list[tuple[str, Dict[str, Any]]]) -> bool:
    """True when every candidate reports the same LocationString.

    The ports of one multi-function adapter share ids and location, so the slot
    is not in doubt even though the candidates are distinct PCIDevices.
    """
    first = candidates[0][1].get("LocationString")
    return bool(first) and all(b.get("LocationString") == first for _, b in candidates)


def merge_chassis_pcie_device_with_systems(
    client: Any,
    chassis_device_path: str,
    chassis_body: Dict[str, Any],
    system_base: str,
) -> Dict[str, Any]:
    """Merge Chassis PCIeDevice response with matching Systems/PCIDevices (HpeServerPciDevice) data.

    Chassis has Manufacturer, Model, Status, FirmwareVersion, etc.; Systems has
    LocationString, StructuredName, bus/location. Returns a single dict suitable
    for Redfish PCIeDevice and for the HPE normalizer (Slot from LocationString/StructuredName).

    Correlation: there is no common field between Chassis PCIeDevice/PCIeFunction and
    Systems HpeServerPciDevice (Chassis does not expose Segment/Bus/Device/Function).
    We match by PCI ids: (VendorID, DeviceID, SubsystemVendorID, SubsystemDeviceID)
    from the Chassis first PCIeFunction vs Systems PCIDevice. When several Systems
    devices share those ids, the Chassis HpeServerDevice with the same real
    SerialNumber links to the right one through DeviceInstances. When that does
    not settle it and the candidates sit in different locations, only fields
    identical across the candidates are merged, so no slot is assigned.
    """
    merged = dict(chassis_body)
    chassis_ids = _get_chassis_pci_ids(client, chassis_device_path, chassis_body)
    if chassis_ids is None:
        return merged
    vid, did, svid, sdid = chassis_ids
    try:
        pcidev_path = system_base.rstrip("/") + "/PCIDevices"
        coll = redfish_get_json(client, pcidev_path)
        candidates: list[tuple[str, Dict[str, Any]]] = []
        for m in coll.get("Members") or []:
            if not isinstance(m, dict):
                continue
            member_url = (m.get("@odata.id") or "").strip()
            if not member_url:
                continue
            member_path = member_url.split("?", 1)[0]
            if not member_path.startswith("/"):
                member_path = "/redfish/v1/" + member_path.lstrip("/")
            member_body = redfish_get_json(client, member_path)
            m_vid = pci_id_to_int(member_body.get("VendorID"))
            m_did = pci_id_to_int(member_body.get("DeviceID"))
            m_svid = pci_id_to_int(member_body.get("SubsystemVendorID"))
            m_sdid = pci_id_to_int(member_body.get("SubsystemDeviceID"))
            if (m_vid, m_did, m_svid or 0, m_sdid or 0) == (vid, did, svid, sdid):
                candidates.append((member_path, member_body))
        chosen: Optional[Dict[str, Any]] = None
        if len(candidates) == 1:
            chosen = candidates[0][1]
        elif len(candidates) > 1:
            chosen = _candidate_from_devices(
                client, chassis_device_path, chassis_body, candidates
            )
            if chosen is None and _same_location(candidates):
                chosen = candidates[0][1]
            if chosen is None:
                _log.debug(
                    "Ambiguous PCI match for %s: %d Systems PCIDevices share ids; "
                    "merging only fields common to all",
                    chassis_device_path,
                    len(candidates),
                )
                for key in _SYSTEMS_PCI_FIELDS_TO_MERGE:
                    values = [body.get(key) for _, body in candidates]
                    if values[0] is not None and all(v == values[0] for v in values):
                        merged[key] = values[0]
        if chosen is not None:
            for key in _SYSTEMS_PCI_FIELDS_TO_MERGE:
                if key in chosen and chosen[key] is not None:
                    merged[key] = chosen[key]
    except Exception:
        pass
    # Chassis PCIeDevice often omits PCI ids at device level; pci.ids Model/Manufacturer
    # need integers on the merged payload (ids come from first PCIeFunction or match).
    if chassis_ids is not None:
        vid, did, svid, sdid = chassis_ids
        if merged.get("VendorID") in (None, ""):
            merged["VendorID"] = vid
        if merged.get("DeviceID") in (None, ""):
            merged["DeviceID"] = did
        if merged.get("SubsystemVendorID") in (None, ""):
            merged["SubsystemVendorID"] = svid
        if merged.get("SubsystemDeviceID") in (None, ""):
            merged["SubsystemDeviceID"] = sdid
    return merged


# -----------------------------------------------------------------------------
# Request rewrite: point Systems/{id}/PCIeDevices at the system's Chassis PCIeDevices
# -----------------------------------------------------------------------------


def _system_id_from_path(path: str) -> Optional[str]:
    m = re.search(r"/redfish/v1/Systems/([^/]+)", path)
    return m.group(1) if m else None


def _hpe_systems_pcie_matches(path: str) -> bool:
    return "/Systems/" in path and "/PCIeDevices" in path


_DEFAULT_CHASSIS = "/redfish/v1/Chassis/1"
_CHASSIS_PCIE_RE = re.compile(r"/redfish/v1/Chassis/[^/]+/PCIeDevices")


def _hpe_systems_pcie_backend_path(path: str, chassis: Optional[str] = None) -> str:
    """Map /redfish/v1/Systems/{id}/PCIeDevices/... to {chassis}/PCIeDevices/...

    ``chassis`` is the system's Chassis; Chassis/1 is used only when no client is
    available to resolve it.
    """
    target = (chassis or _DEFAULT_CHASSIS).lstrip("/")
    return re.sub(
        r"/redfish/v1/Systems/[^/]+",
        lambda _m: "/" + target,
        path,
        count=1,
    )


def _hpe_systems_pcie_response_rewrite(
    path: str, chassis: Optional[str] = None
) -> tuple[str, str]:
    """Return (from_prefix, to_prefix) for rewriting Chassis URIs to Systems in response.

    Chassis/1 is used only when no client is available to resolve ``chassis``.
    """
    from_prefix = f"{chassis or _DEFAULT_CHASSIS}/PCIeDevices"
    parts = path.strip("/").split("/")
    try:
        i = parts.index("v1")
    except ValueError:
        return from_prefix, "/redfish/v1/Systems/1/PCIeDevices"
    after = parts[i + 1 :]
    if len(after) >= 3 and after[0] == "Systems" and after[2] == "PCIeDevices":
        system_id = after[1]
        to_prefix = f"/redfish/v1/Systems/{system_id}/PCIeDevices"
    else:
        to_prefix = "/redfish/v1/Systems/1/PCIeDevices"
    return from_prefix, to_prefix


# -----------------------------------------------------------------------------
# Conditional fallback when the Chassis PCIeDevices collection is empty (e.g. DL360, DL380)
# -----------------------------------------------------------------------------


def hpe_chassis_pcie_devices_empty(
    client: Any, chassis: str = _DEFAULT_CHASSIS
) -> bool:
    """Return True if {chassis}/PCIeDevices is missing, has no Members, or all Members lack @odata.id.

    Some iLO firmware versions return Members with blank @odata.id, making
    the collection unusable even though Members@odata.count > 0.
    """
    try:
        coll = redfish_get_json(client, f"{chassis}/PCIeDevices")
        if not coll:
            return True
        members = coll.get("Members") or []
        return not any(
            isinstance(m, dict) and (m.get("@odata.id") or "").strip() for m in members
        )
    except Exception:
        return True


def hpe_systems_pcie_fallback_rewrite(path: str) -> tuple[str, str, str]:
    """When chassis PCIeDevices is empty: backend from Systems/PCIDevices, rewrite PCIDevices -> PCIeDevices.

    Returns (backend_path, from_prefix, to_prefix).
    """
    backend_path = path.replace("/PCIeDevices", "/PCIDevices")
    # Extract system id from path: /redfish/v1/Systems/1/PCIeDevices/3 -> 1
    parts = path.strip("/").split("/")
    try:
        i = parts.index("Systems")
        if i + 1 < len(parts):
            system_id = parts[i + 1]
        else:
            system_id = "1"
    except ValueError:
        system_id = "1"
    from_prefix = f"/redfish/v1/Systems/{system_id}/PCIDevices"
    to_prefix = f"/redfish/v1/Systems/{system_id}/PCIeDevices"
    return (backend_path, from_prefix, to_prefix)


def _first_int(*values: Any) -> int | None:
    """First value that is an int, or a decimal string, as an int. None otherwise."""
    for v in values:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip(), 10)
    return None


def _pci_id_hex(val: Any) -> str | None:
    """Format PCI id as 0xXXXX for Redfish; None when the BMC did not send one."""
    n = pci_id_to_int(val)
    return None if n is None else f"0x{n:04X}"


def build_synthetic_pcie_function_from_pcidevice(
    device_body: Dict[str, Any],
    function_odata_id: str,
    device_odata_id: str,
    *,
    function_index: int = 1,
) -> Dict[str, Any]:
    """Build a minimal PCIeFunction resource from HpeServerPciDevice (or normalized PCIeDevice) for gofish.

    function_index is 1-based; used for Id, FunctionId, and Name (e.g. "Function 2").
    """
    oem = (device_body.get("Oem") or {}).get("Hpe") or {}
    vid = oem.get("VendorID") or device_body.get("VendorID")
    did = oem.get("DeviceID") or device_body.get("DeviceID")
    svid = oem.get("SubsystemVendorID") or device_body.get("SubsystemVendorID")
    sdid = oem.get("SubsystemDeviceID") or device_body.get("SubsystemDeviceID")
    class_code = oem.get("ClassCode") or device_body.get("ClassCode")
    subclass = oem.get("SubclassCode") or device_body.get("SubclassCode")

    raw_for_norm: Any = None
    if isinstance(class_code, int) and isinstance(subclass, int):
        raw_for_norm = (class_code << 16) | (subclass << 8)
    elif isinstance(class_code, str):
        raw_for_norm = class_code
    elif isinstance(class_code, int):
        raw_for_norm = class_code

    class_hex: str | None = None
    if raw_for_norm is not None:
        class_hex_o = normalize_pci_class_code(raw_for_norm)
        class_hex = class_hex_o if isinstance(class_hex_o, str) else None

    from .base import device_class_from_pci_class

    base_class: int | None = None
    if class_hex is not None:
        try:
            base_class = (int(class_hex, 16) >> 16) & 0xFF
        except (ValueError, TypeError):
            base_class = None
    # DeviceClass is an enum without null: left out when the class is unknown.
    device_class = device_class_from_pci_class(base_class)
    function_number = _first_int(
        oem.get("FunctionNumber"), device_body.get("FunctionNumber")
    )
    # Keep function Name aligned with the underlying PCIDevice Name so the
    # collector's device.Name (taken from the first function) matches the
    # adapter name, even for multi-function devices.
    name = (device_body.get("Name") or "Function 1").strip() or "Function 1"
    out: Dict[str, Any] = {
        "@odata.context": "/redfish/v1/$metadata#PCIeFunction.PCIeFunction",
        "@odata.id": function_odata_id,
        "@odata.type": BaseSystemsPCIeFunctionNormalizer().field_map()["@odata.type"],
        "Id": str(function_index),
        "Name": name,
        "Description": device_body.get("Description") or "",
        # FunctionId is the BMC's FunctionNumber; null when the BMC did not send it.
        "FunctionId": function_number,
        "ClassCode": class_hex,
        "DeviceId": _pci_id_hex(did),
        "VendorId": _pci_id_hex(vid),
        "SubsystemId": _pci_id_hex(sdid),
        "SubsystemVendorId": _pci_id_hex(svid),
        "Status": {},
        "Links": {"PCIeDevice": {"@odata.id": device_odata_id}},
        "Oem": {},
    }
    # FunctionType is not reported by HPE; omitted rather than assumed "Physical".
    if device_class is not None:
        out["DeviceClass"] = device_class
    return out


def build_synthetic_pcie_function_collection(
    collection_odata_id: str,
    member_odata_ids: list[str],
) -> Dict[str, Any]:
    """Build a PCIeFunctionCollection for synthetic HPE functions."""
    members = [{"@odata.id": mid} for mid in member_odata_ids]
    return {
        "@odata.context": "/redfish/v1/$metadata#PCIeFunctionCollection.PCIeFunctionCollection",
        "@odata.id": collection_odata_id,
        "@odata.type": PCIE_FUNCTION_COLLECTION_MAPPING["@odata.type"],
        "Members": members,
        "Members@odata.count": len(members),
        "Description": "Collection of PCIe Functions",
        "Name": "PCIeFunctionCollection",
        "Oem": {},
    }


# -----------------------------------------------------------------------------
# Grouping: same physical device = same (Segment,Bus,Device,VendorID,DeviceID,Subsystem*)
# -----------------------------------------------------------------------------


def _physical_device_key(d: Dict[str, Any]) -> tuple:
    """Key for grouping HpeServerPciDevice by physical device."""
    return (
        d.get("SegmentNumber"),
        d.get("BusNumber"),
        d.get("DeviceNumber"),
        d.get("VendorID"),
        d.get("DeviceID"),
        d.get("SubsystemVendorID"),
        d.get("SubsystemDeviceID"),
    )


def get_hpe_pcidevice_grouping(
    client: Any,
    collection_path: str,
) -> Dict[str, list[str]]:
    """Group backend PCIDevices by physical device. Returns group_id -> [backend_id, ...] sorted by FunctionNumber then Id.

    collection_path should be the backend collection URL (e.g. /redfish/v1/Systems/1/PCIDevices).
    group_id is the minimum Id in the group (string). Used to collapse multiple
    functions (e.g. PCIDevices/1 and /2 same card) into one PCIeDevice with N functions.
    """
    out: Dict[str, list[str]] = {}
    try:
        coll = redfish_get_json(client, collection_path)
        if not coll:
            return out
        members = coll.get("Members") or []
        if not members:
            return out
        # Collect (key, id, function_number) for each member
        entries: list[tuple[tuple, str, int]] = []
        for m in members:
            if not isinstance(m, dict):
                continue
            odata_id = (m.get("@odata.id") or "").strip()
            if not odata_id:
                continue
            path = odata_id.split("?", 1)[0]
            if not path.startswith("/"):
                path = "/redfish/v1/" + path.lstrip("/")
            dev = redfish_get_json(client, path)
            if not dev:
                continue
            key = _physical_device_key(dev)
            dev_id = dev.get("Id")
            if dev_id is None:
                parts = path.rstrip("/").split("/")
                dev_id = parts[-1] if parts else ""
            dev_id = str(dev_id)
            fn = dev.get("FunctionNumber")
            if not isinstance(fn, int):
                fn = 0
            entries.append((key, dev_id, fn))
        # Group by key; within group sort by FunctionNumber then Id
        from collections import defaultdict

        by_key: Dict[tuple, list[tuple[str, int]]] = defaultdict(list)
        for key, dev_id, fn in entries:
            by_key[key].append((dev_id, fn))
        for key, ids_fns in by_key.items():
            ids_fns.sort(key=lambda x: (x[1], x[0]))
            ordered_ids = [x[0] for x in ids_fns]
            group_id = min(
                ordered_ids, key=lambda i: (int(i) if str(i).isdigit() else 999999, i)
            )
            out[group_id] = ordered_ids
    except Exception:
        pass
    return out


# -----------------------------------------------------------------------------
# Request rewrite hooks (proxy calls these; no vendor logic in proxy)
# -----------------------------------------------------------------------------


def _hpe_resolve_backend(client: Any, path: str) -> tuple[str, str, str]:
    """Resolve backend: use Systems/PCIDevices when the system's Chassis PCIeDevices is empty."""
    begin_system_chassis_memo()
    system_id = _system_id_from_path(path)
    chassis = chassis_for_system(client, system_id) if system_id else None
    default_backend = _hpe_systems_pcie_backend_path(path, chassis)
    from_default, to_default = _hpe_systems_pcie_response_rewrite(path, chassis)
    if not _CHASSIS_PCIE_RE.search(default_backend):
        return (default_backend, from_default, to_default)
    if not hpe_chassis_pcie_devices_empty(client, chassis or _DEFAULT_CHASSIS):
        return (default_backend, from_default, to_default)
    return hpe_systems_pcie_fallback_rewrite(path)


def _hpe_on_backend_error(
    call: RewriteCall, status: int
) -> Optional[tuple[Dict[str, Any], int]]:
    """When backend returns non-200 and path is PCIeFunctions, synthesize collection or function.

    Uses get_hpe_pcidevice_grouping so multi-function devices (same bus/device)
    produce N PCIeFunctions, each built from the corresponding backend PCIDevice.
    """
    client, path = call.client, call.path
    from_prefix, to_prefix = call.from_prefix, call.to_prefix
    if "/PCIeDevices/" not in path or "/PCIeFunctions" not in path:
        return None
    path_parts = path.rstrip("/").split("/")
    try:
        pcie_dev_idx = path_parts.index("PCIeDevices")
        if pcie_dev_idx + 1 >= len(path_parts):
            return None
        device_id = path_parts[pcie_dev_idx + 1]
        device_odata_id = f"{to_prefix.rstrip('/')}/{device_id}"
        collection_path = from_prefix.rstrip("/")
        grouping = get_hpe_pcidevice_grouping(client, collection_path)
        backend_ids = grouping.get(device_id, [device_id])
        # Request for single function: .../PCIeFunctions/{n}
        if path_parts[-2] == "PCIeFunctions" and path_parts[-1] != "PCIeFunctions":
            func_idx_str = path_parts[-1]
            try:
                func_idx = int(func_idx_str)
            except ValueError:
                return None
            if func_idx < 1 or func_idx > len(backend_ids):
                return None
            bid = backend_ids[func_idx - 1]
            dev_body = redfish_get_json(client, f"{collection_path}/{bid}")
            if not dev_body:
                return None
            func_odata_id = f"{device_odata_id}/PCIeFunctions/{func_idx}"
            body = build_synthetic_pcie_function_from_pcidevice(
                dev_body,
                func_odata_id,
                device_odata_id,
                function_index=func_idx,
            )
            return (body, 200)
        # Request for collection: .../PCIeFunctions
        member_ids = [
            f"{device_odata_id}/PCIeFunctions/{i}"
            for i in range(1, len(backend_ids) + 1)
        ]
        coll_odata_id = f"{device_odata_id}/PCIeFunctions"
        body = build_synthetic_pcie_function_collection(coll_odata_id, member_ids)
        return (body, 200)
    except (ValueError, IndexError, Exception):
        return None


def _evaluate_hpe_systems_pcie_device(
    body: Dict[str, Any], client: Any
) -> Dict[str, Any]:
    """Apply the HPE Systems PCIeDevice field map.

    The client path is a rewrite of Chassis/PCIeDevices, so it is not a backend
    resource the proxy can classify. This module owns that normalization.
    """
    ctx = NormalizationContext(
        data=body,
        client=client,
        logger=logging.getLogger(__name__),
        vendor="HPE",
    )
    return normalize_resource(HpeSystemsPCIeDeviceNormalizer(), ctx)


def _hpe_after_200_merge(call: RewriteCall, body: Dict[str, Any]) -> Dict[str, Any]:
    """Merge Chassis PCIeDevice with Systems/PCIDevices when backend is Chassis (single device)."""
    client, path, backend_path = call.client, call.path, call.backend_path
    to_prefix = call.to_prefix
    path_parts = [part for part in path.split("/") if part]
    if path_parts and path_parts[-1] in ("PCIeDevices", "PCIDevices"):
        ctx = NormalizationContext(
            data=body if isinstance(body, dict) else {},
            client=client,
            logger=logging.getLogger(__name__),
            vendor="HPE",
            resource_path=path,
        )
        return evaluate(COLLECTION_MAPPING, ctx)
    parts = backend_path.rstrip("/").split("/")
    if len(parts) != 7 or parts[5] != "PCIeDevices":
        return body
    if not _CHASSIS_PCIE_RE.search(backend_path):
        return body
    system_base = to_prefix[: -len("/PCIeDevices")]
    merged = merge_chassis_pcie_device_with_systems(
        client,
        backend_path,
        body,
        system_base,
    )
    return _evaluate_hpe_systems_pcie_device(merged, client)


def _hpe_should_normalize_single(path: str, backend_path: str) -> bool:
    """True when the proxy should run the registered single-resource normalizer.

    A Chassis PCIeDevice served at Systems/PCIeDevices is normalized in
    ``_hpe_after_200_merge``. Asking the proxy to normalize that client path
    looks up a URL the BMC does not have.
    """
    parts = backend_path.rstrip("/").split("/")
    if len(parts) != 7:
        return False
    if parts[5] == "PCIeDevices":
        return False
    if parts[5] == "PCIDevices":
        return path.count("PCIeDevices") >= 1 and "/PCIeFunctions" not in path
    return False


register_request_rewrite(
    RequestRewriteRule(
        vendor="HPE",
        matches=_hpe_systems_pcie_matches,
        get_backend_path=_hpe_systems_pcie_backend_path,
        get_response_rewrite=_hpe_systems_pcie_response_rewrite,
        resolve_backend=_hpe_resolve_backend,
        on_backend_error=_hpe_on_backend_error,
        after_200_merge=_hpe_after_200_merge,
        should_normalize_single=_hpe_should_normalize_single,
    )
)
