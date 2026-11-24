# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Helpers for exposing HPE SmartStorage as standard Redfish Storage."""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from redpool.redfish_client import redfish_get_json

from ..._shared.system_chassis import chassis_for_system
from ...vendor_id import manufacturer_from_model

_SYSTEM_STORAGE_RE = re.compile(r"^/redfish/v1/Systems/([^/]+)/Storage(?:/(.*))?$")
_SMARTSTORAGE_MEMBER_RE = re.compile(
    r"^/redfish/v1/Systems/([^/]+)/SmartStorage/ArrayControllers/([^/]+)"
    r"(?:/(DiskDrives|LogicalDrives)/([^/]+))?$"
)


def hpe_storage_request_parts(path: str) -> Optional[Tuple[str, List[str]]]:
    """Return ``(system_id, suffix_parts)`` for canonical Storage paths."""
    match = _SYSTEM_STORAGE_RE.match(path.rstrip("/"))
    if not match:
        return None
    suffix = match.group(2) or ""
    return match.group(1), [p for p in suffix.split("/") if p]


def hpe_smartstorage_member_parts(path: str) -> Optional[Tuple[str, str, str, str]]:
    """Return ``(system_id, storage_id, kind, member_id)`` for a SmartStorage member.

    ``kind`` is ``DiskDrives`` or ``LogicalDrives``. For the array controller
    itself, ``kind`` and ``member_id`` are empty.
    """
    match = _SMARTSTORAGE_MEMBER_RE.match(path.rstrip("/"))
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3) or "", match.group(4) or ""


DEFAULT_HPE_CHASSIS = "/redfish/v1/Chassis/1"


def hpe_chassis_path(client: Any, system_id: str) -> str:
    """The system's Chassis path; Chassis/1 only when it cannot be resolved."""
    if client is None or not system_id:
        return DEFAULT_HPE_CHASSIS
    return chassis_for_system(client, system_id) or DEFAULT_HPE_CHASSIS


def hpe_smartstorage_path(system_id: str, *parts: str) -> str:
    base = f"/redfish/v1/Systems/{system_id}/SmartStorage"
    return "/".join([base, *[p.strip("/") for p in parts if p]])


def canonical_storage_path(system_id: str, storage_id: str, *parts: str) -> str:
    base = f"/redfish/v1/Systems/{system_id}/Storage/{storage_id}"
    return "/".join([base, *[p.strip("/") for p in parts if p]])


def storage_id_from_array_controller(controller: Dict[str, Any]) -> str:
    value = controller.get("Id")
    if value is None or str(value).strip() == "":
        value = controller.get("@odata.id", "").rstrip("/").split("/")[-1]
    return str(value or "0")


def safe_redfish_get(client: Any, path: str) -> Dict[str, Any]:
    try:
        body = redfish_get_json(client, path)
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def native_storage_path(client: Any, system_id: str, storage_id: str) -> Optional[str]:
    """Native ``Storage/{id}`` for the array controller ``storage_id``, matched by model or serial."""
    controller = safe_redfish_get(
        client,
        hpe_smartstorage_path(system_id, "ArrayControllers", storage_id),
    )
    model = controller.get("Model")
    serial = controller.get("SerialNumber")
    if isinstance(serial, str):
        serial = serial.strip()
    if not model and not serial:
        return None
    collection = safe_redfish_get(client, f"/redfish/v1/Systems/{system_id}/Storage")
    found: List[str] = []
    for member in collection.get("Members") or []:
        if not isinstance(member, dict):
            continue
        storage_path = member.get("@odata.id")
        if not isinstance(storage_path, str) or not storage_path.strip():
            continue
        storage_path = storage_path.rstrip("/")
        storage = safe_redfish_get(client, storage_path)
        if model and storage.get("Name") == model:
            found.append(storage_path)
            continue
        controllers_link = storage.get("Controllers") or {}
        controllers_path = (
            controllers_link.get("@odata.id")
            if isinstance(controllers_link, dict)
            else None
        )
        if not controllers_path:
            continue
        controllers = safe_redfish_get(client, controllers_path)
        for controller_member in controllers.get("Members") or []:
            if not isinstance(controller_member, dict):
                continue
            controller_path = controller_member.get("@odata.id")
            if not isinstance(controller_path, str) or not controller_path.strip():
                continue
            native = safe_redfish_get(client, controller_path)
            native_serial = native.get("SerialNumber")
            if isinstance(native_serial, str):
                native_serial = native_serial.strip()
            if (model and native.get("Model") == model) or (
                serial and native_serial == serial
            ):
                found.append(storage_path)
                break
    if len(found) == 1:
        return found[0]
    return None


def native_storage_for_enrichment(
    client: Any, system_id: str, storage_id: str
) -> Optional[str]:
    """The native Storage that enriches this array: by array controller id, else by its own id.

    Gen10 requests may use the native Storage id (``DE07A000``) rather than the array
    controller id (``0``). The lookup only enriches fields; it does not change which
    documents are served.
    """
    by_array = native_storage_path(client, system_id, storage_id)
    if by_array:
        return by_array
    direct = f"/redfish/v1/Systems/{system_id}/Storage/{storage_id}"
    if safe_redfish_get(client, direct).get("Controllers"):
        return direct
    return None


def native_member(
    client: Any, system_id: str, storage_id: str, kind: str, member_id: str
) -> Dict[str, Any]:
    """The native Storage ``kind/member_id`` document, or {} when there is no native Storage."""
    native = native_storage_for_enrichment(client, system_id, storage_id)
    if not native:
        return {}
    return safe_redfish_get(client, f"{native}/{kind}/{member_id}")


def native_controller(client: Any, system_id: str, storage_id: str) -> Dict[str, Any]:
    """The native controller of this array, when the native Storage has exactly one."""
    native = native_storage_for_enrichment(client, system_id, storage_id)
    if not native:
        return {}
    members = safe_redfish_get(client, f"{native}/Controllers").get("Members") or []
    if len(members) != 1 or not isinstance(members[0], dict):
        return {}
    controller_path = members[0].get("@odata.id")
    if not isinstance(controller_path, str) or not controller_path.strip():
        return {}
    return safe_redfish_get(client, controller_path)


_SMARTSTORAGE_NATIVE_KIND = {"DiskDrives": "Drives", "LogicalDrives": "Volumes"}
_STORAGE_MEMBER_RE = re.compile(
    r"^/redfish/v1/Systems/([^/]+)/Storage/([^/]+)/(Drives|Volumes)/([^/]+)$"
)


def native_member_for_path(client: Any, path: str) -> Dict[str, Any]:
    """The native Storage member that enriches a SmartStorage or Storage Drive/Volume path."""
    if client is None:
        return {}
    smart = hpe_smartstorage_member_parts(path)
    if smart is not None:
        system_id, storage_id, kind, member_id = smart
        native_kind = _SMARTSTORAGE_NATIVE_KIND.get(kind)
    else:
        match = _STORAGE_MEMBER_RE.match(path.rstrip("/"))
        if match is None:
            return {}
        system_id, storage_id, native_kind, member_id = match.groups()
    if not native_kind or not member_id:
        return {}
    return native_member(client, system_id, storage_id, native_kind, member_id)


def collection_body(
    path: str,
    members: List[Dict[str, str]],
    name: str,
    description: str,
    odata_context: str,
    odata_type: str,
) -> Dict[str, Any]:
    return {
        "@odata.context": odata_context,
        "@odata.id": path,
        "@odata.type": odata_type,
        "Name": name,
        "Description": description,
        "Members": members,
        "Members@odata.count": len(members),
    }


def member_links(
    collection: Dict[str, Any], from_prefix: str, to_prefix: str
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for member in collection.get("Members") or []:
        if not isinstance(member, dict):
            continue
        odata_id = member.get("@odata.id")
        if not isinstance(odata_id, str) or not odata_id:
            continue
        out.append({"@odata.id": odata_id.replace(from_prefix, to_prefix)})
    return out


def firmware_version(data: Dict[str, Any]) -> Optional[str]:
    fw = data.get("FirmwareVersion")
    if isinstance(fw, dict):
        current = fw.get("Current")
        if isinstance(current, dict):
            value = current.get("VersionString")
            if value is not None:
                return str(value)
    if isinstance(fw, str):
        return fw
    return None


def mib_to_bytes(value: Any) -> Optional[int]:
    try:
        return int(value) * 1024 * 1024
    except (TypeError, ValueError):
        return None


def logical_blocks_to_bytes(data: Dict[str, Any]) -> Optional[int]:
    try:
        return int(data["CapacityLogicalBlocks"]) * int(data["BlockSizeBytes"])
    except (KeyError, TypeError, ValueError):
        return None


def mbps_to_gbps(value: Any) -> Optional[float]:
    try:
        return float(value) / 1000.0
    except (TypeError, ValueError):
        return None


def hpe_raid_to_redfish(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.lower().startswith("raid"):
        return "RAID" + raw[4:]
    if raw.lower() == "none":
        return "None"
    return f"RAID{raw}"


def hpe_location_to_physical_location(location: Any) -> Dict[str, Any]:
    if not isinstance(location, str) or not location:
        return {}
    parts = location.split(":")
    bay: Optional[int] = None
    if len(parts) >= 3:
        try:
            bay = int(parts[2])
        except ValueError:
            bay = None
    part_location: Dict[str, Any] = {
        "LocationType": "Bay",
        "ServiceLabel": f"Port={location}",
    }
    if bay is not None:
        part_location["LocationOrdinalValue"] = bay
    return {"PartLocation": part_location}


def redpool_oem(
    kind: str, data: Dict[str, Any], fields: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Keep the source ``Oem`` and attach ``Oem.Redpool.HpeSmartStorage``.

    ``fields`` holds the named values a consumer reads. The source payload is not embedded.
    """
    src = data.get("Oem")
    oem: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    existing = oem.get("Redpool")
    redpool: Dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    hpe: Dict[str, Any] = {"Kind": kind}
    for key, value in (fields or {}).items():
        if value is not None:
            hpe[key] = value
    redpool["HpeSmartStorage"] = hpe
    oem["Redpool"] = redpool
    return oem


def build_storage_collection_from_array_controllers(
    path: str,
    system_id: str,
    array_controllers: Dict[str, Any],
) -> Dict[str, Any]:
    members = member_links(
        array_controllers,
        hpe_smartstorage_path(system_id, "ArrayControllers"),
        f"/redfish/v1/Systems/{system_id}/Storage",
    )
    return collection_body(
        path,
        members,
        "StorageCollection",
        "Collection of Storage subsystems",
        "/redfish/v1/$metadata#StorageCollection.StorageCollection",
        "#StorageCollection.StorageCollection",
    )


def build_storage_resource(
    path: str,
    system_id: str,
    controller: Dict[str, Any],
    *,
    disk_collection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    storage_id = storage_id_from_array_controller(controller)
    storage_base = f"/redfish/v1/Systems/{system_id}/Storage/{storage_id}"
    disk_base = hpe_smartstorage_path(
        system_id, "ArrayControllers", storage_id, "DiskDrives"
    )
    drives = member_links(disk_collection or {}, disk_base, f"{storage_base}/Drives")
    status = dict(controller.get("Status") or {})
    if "Health" in status and "HealthRollup" not in status:
        status["HealthRollup"] = status["Health"]
    return {
        "@odata.context": "/redfish/v1/$metadata#Storage.Storage",
        "@odata.id": path,
        "@odata.type": "#Storage.v1_16_0.Storage",
        "Id": storage_id,
        "Name": controller.get("Model")
        or controller.get("Name")
        or "HPE Smart Storage",
        "Status": status,
        "Drives": drives,
        "Drives@odata.count": len(drives),
        "Volumes": {"@odata.id": f"{storage_base}/Volumes"},
        "Controllers": {"@odata.id": f"{storage_base}/Controllers"},
        "Oem": redpool_oem("ArrayController", controller),
    }


_DRIVE_STATUS_INDICATOR = {
    "OK",
    "Fail",
    "Rebuild",
    "PredictiveFailureAnalysis",
    "Hotspare",
    "InACriticalArray",
    "InAFailedArray",
}


def _drive_status_indicator(drive: Dict[str, Any]) -> Optional[str]:
    """Drive.StatusIndicator is not Status.Health. ``Warning`` is not in that enum."""
    status = drive.get("Status")
    health = status.get("Health") if isinstance(status, dict) else None
    if health in _DRIVE_STATUS_INDICATOR:
        return health
    return None


def same_capacity(native_bytes: Any, smart_bytes: Optional[int]) -> bool:
    """True when the native and SmartStorage capacities agree to within a MiB.

    SmartStorage and the native Storage view address the same disk by the same index.
    Matching capacity is the check that they are really the same disk, since the
    serial numbers of a sanitized capture are identical.
    """
    if not isinstance(native_bytes, int) or not smart_bytes:
        return False
    return abs(native_bytes - smart_bytes) <= 1024 * 1024


def build_drive_resource(
    path: str,
    drive: Dict[str, Any],
    native: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    capacity = logical_blocks_to_bytes(drive)
    if capacity is None:
        capacity = mib_to_bytes(drive.get("CapacityMiB"))
    native = (
        native
        if same_capacity(native and native.get("CapacityBytes"), capacity)
        else {}
    )
    speed = mbps_to_gbps(drive.get("InterfaceSpeedMbps"))
    encrypted = drive.get("EncryptedDrive")
    encryption_ability = "SelfEncryptingDrive" if encrypted else "None"
    encryption_status = "Unlocked" if encrypted else "Unencrypted"
    # HPE SSDEnduranceUtilizationPercentage is wear used (0-100); Redfish wants life left.
    life_left = None
    util = drive.get("SSDEnduranceUtilizationPercentage")
    if isinstance(util, (int, float)) and 0 <= util <= 100:
        life_left = 100 - util
    elif isinstance(util, (int, float)):
        # Some firmware reports values outside 0-100; keep raw in Oem and leave life unset.
        life_left = None
    temp = drive.get("CurrentTemperatureCelsius")
    oem = redpool_oem("DiskDrive", drive)
    rp = oem["Redpool"]["HpeSmartStorage"]
    if isinstance(temp, (int, float)):
        rp["TemperatureCelsius"] = temp
    for key in ("UncorrectedReadErrors", "UncorrectedWriteErrors"):
        if drive.get(key) is not None:
            rp[key] = drive.get(key)
    body = {
        "@odata.context": "/redfish/v1/$metadata#Drive.Drive",
        "@odata.etag": drive.get("@odata.etag"),
        "@odata.id": path,
        "@odata.type": "#Drive.v1_19_0.Drive",
        "Id": str(drive.get("Id") or path.rstrip("/").split("/")[-1]),
        "Name": drive.get("Name") or drive.get("Model"),
        "Description": drive.get("Description") or drive.get("Name"),
        "Status": drive.get("Status", {}),
        "Model": drive.get("Model"),
        "Manufacturer": drive.get("Manufacturer"),
        "SerialNumber": drive.get("SerialNumber"),
        "Revision": firmware_version(drive),
        "MediaType": drive.get("MediaType"),
        "Protocol": drive.get("InterfaceType"),
        "CapacityBytes": capacity,
        "BlockSizeBytes": drive.get("BlockSizeBytes"),
        # The interface speed is a link rate: report it once, as negotiated speed.
        "CapableSpeedGbs": native.get("CapableSpeedGbs"),
        "NegotiatedSpeedGbs": speed,
        "PredictedMediaLifeLeftPercent": life_left,
        # SmartStorage does not report a predictive-failure flag; the native drive does,
        # and it is used only when the disk matches.
        "FailurePredicted": native.get("FailurePredicted"),
        "StatusIndicator": _drive_status_indicator(drive),
        "EncryptionAbility": encryption_ability,
        "EncryptionStatus": encryption_status,
        "PhysicalLocation": hpe_location_to_physical_location(drive.get("Location")),
        "Location": [
            {
                "Info": drive.get("Location"),
                "InfoFormat": drive.get("LocationFormat"),
            }
        ],
        "Links": {},
        "Oem": oem,
    }
    if body.get("StatusIndicator") is None:
        body.pop("StatusIndicator", None)
    if native.get("Identifiers") and not body.get("Identifiers"):
        body["Identifiers"] = native["Identifiers"]
    return body


def build_volume_resource(
    path: str,
    volume: Dict[str, Any],
    *,
    data_drives: Optional[Dict[str, Any]] = None,
    system_id: Optional[str] = None,
    storage_id: Optional[str] = None,
    native: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    links: Dict[str, Any] = {}
    if data_drives and system_id is not None and storage_id is not None:
        source = hpe_smartstorage_path(
            system_id,
            "ArrayControllers",
            storage_id,
            "DiskDrives",
        )
        target = canonical_storage_path(system_id, storage_id, "Drives")
        drives = member_links(data_drives, source, target)
        links["Drives"] = drives
        links["Drives@odata.count"] = len(drives)
    name = volume.get("LogicalDriveName") or volume.get("Name")
    native = (
        native
        if same_capacity(
            native and native.get("CapacityBytes"),
            mib_to_bytes(volume.get("CapacityMiB")),
        )
        else {}
    )
    cache = {
        key: native[key]
        for key in ("ReadCachePolicy", "WriteCachePolicy", "IOPerfModeEnabled")
        if native.get(key) is not None
    }
    return {
        "@odata.context": "/redfish/v1/$metadata#Volume.Volume",
        "@odata.etag": volume.get("@odata.etag"),
        "@odata.id": path,
        "@odata.type": "#Volume.v1_10_0.Volume",
        "Id": str(volume.get("Id") or path.rstrip("/").split("/")[-1]),
        "Name": name,
        "DisplayName": name,
        "Description": volume.get("Description"),
        "Status": volume.get("Status", {}),
        "CapacityBytes": mib_to_bytes(volume.get("CapacityMiB")),
        "BlockSizeBytes": volume.get("BlockSizeBytes") or native.get("BlockSizeBytes"),
        **cache,
        "StripSizeBytes": volume.get("StripeSizeBytes"),
        "OptimumIOSizeBytes": volume.get("StripeSizeBytes"),
        "RAIDType": hpe_raid_to_redfish(volume.get("Raid")),
        "Encrypted": bool(volume.get("LogicalDriveEncryption", False)),
        "EncryptionTypes": [],
        "Identifiers": [
            {
                "DurableName": volume.get("VolumeUniqueIdentifier"),
                "DurableNameFormat": "NAA",
            }
        ]
        if volume.get("VolumeUniqueIdentifier")
        else [],
        "Links": links,
        "Oem": redpool_oem("LogicalDrive", volume),
    }


def _storage_controller_location(controller: Dict[str, Any]) -> Dict[str, Any]:
    """SmartStorage sends a slot string. Native controllers already send Location."""
    loc = controller.get("Location")
    if isinstance(loc, dict):
        part = loc.get("PartLocation")
        if isinstance(part, dict):
            label = part.get("ServiceLabel")
            if isinstance(label, dict):
                inner = label.get("PartLocation")
                if isinstance(inner, dict) and isinstance(
                    inner.get("ServiceLabel"), str
                ):
                    return {"PartLocation": inner}
        return loc
    if isinstance(loc, str) and loc.strip():
        return {
            "PartLocation": {
                "LocationType": "Slot",
                "ServiceLabel": loc.strip(),
            }
        }
    return {}


def build_storage_controller_resource(
    path: str,
    controller: Dict[str, Any],
    *,
    battery_count: int = 0,
    system_id: Optional[str] = None,
    storage_id: Optional[str] = None,
    identifiers: Optional[list] = None,
    native: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    native = native if native and native.get("Model") == controller.get("Model") else {}
    controller_id = str(controller.get("Id") or path.rstrip("/").split("/")[-1])
    battery_base = f"{path}/Batteries"
    batteries = [
        {"@odata.id": f"{battery_base}/{idx + 1}"} for idx in range(battery_count)
    ]
    links: Dict[str, Any] = {}
    if batteries:
        links["Batteries"] = batteries
        links["Batteries@odata.count"] = len(batteries)
    device_protocols = []
    if controller.get("InternalPortCount") or controller.get("ExternalPortCount"):
        device_protocols = ["SAS", "SATA"]
    serial = controller.get("SerialNumber")
    if isinstance(serial, str):
        serial = serial.strip()
    return {
        "@odata.context": "/redfish/v1/$metadata#StorageController.StorageController",
        "@odata.etag": controller.get("@odata.etag"),
        "@odata.id": path,
        "@odata.type": "#StorageController.v1_7_0.StorageController",
        "Id": controller_id,
        "Name": controller.get("Model") or controller.get("Name"),
        "Description": controller.get("Description"),
        "Status": controller.get("Status", {}),
        "Manufacturer": manufacturer_from_model(controller.get("Model")),
        "Model": controller.get("Model"),
        "SerialNumber": serial,
        "PartNumber": controller.get("ControllerPartNumber"),
        "FirmwareVersion": firmware_version(controller),
        "Identifiers": (
            identifiers
            if identifiers is not None
            else controller.get("Identifiers") or []
        ),
        "SupportedControllerProtocols": ["PCIe"],
        "SupportedDeviceProtocols": device_protocols,
        "SupportedRAIDTypes": native.get("SupportedRAIDTypes")
        or [
            "RAID0",
            "RAID1",
            "RAID10",
            "RAID5",
            "RAID50",
            "RAID6",
            "RAID60",
            "RAID1Triple",
            "RAID10Triple",
            "None",
        ],
        **{
            key: native[key]
            for key in ("SpeedGbps", "CacheSummary")
            if native.get(key) is not None
        },
        "Location": _storage_controller_location(controller),
        "Links": links,
        "Oem": redpool_oem("ArrayController", controller),
    }


def hpe_batteries_from_chassis(chassis: Dict[str, Any]) -> List[Dict[str, Any]]:
    hpe = (chassis.get("Oem") or {}).get("Hpe") or {}
    batteries = hpe.get("SmartStorageBattery") or []
    return [b for b in batteries if isinstance(b, dict)]


def build_battery_collection(path: str, chassis: Dict[str, Any]) -> Dict[str, Any]:
    batteries = hpe_batteries_from_chassis(chassis)
    members = [{"@odata.id": f"{path}/{idx + 1}"} for idx in range(len(batteries))]
    return collection_body(
        path,
        members,
        "BatteryCollection",
        "Collection of storage controller batteries",
        "/redfish/v1/$metadata#BatteryCollection.BatteryCollection",
        "#BatteryCollection.BatteryCollection",
    )


def build_battery_resource(
    path: str,
    battery: Dict[str, Any],
) -> Dict[str, Any]:
    idx = str(battery.get("Index") or path.rstrip("/").split("/")[-1])
    body: Dict[str, Any] = {
        "@odata.context": "/redfish/v1/$metadata#Battery.Battery",
        "@odata.id": path,
        "@odata.type": "#Battery.v1_5_0.Battery",
        "Id": idx,
        "Name": battery.get("ProductName") or f"Smart Storage Battery {idx}",
        "Description": battery.get("ProductName") or "HPE Smart Storage Battery",
        "Manufacturer": manufacturer_from_model(
            battery.get("ProductName") or battery.get("Model")
        ),
        "Model": battery.get("Model"),
        "SerialNumber": battery.get("SerialNumber"),
        "SparePartNumber": battery.get("SparePartNumber"),
        "FirmwareVersion": battery.get("FirmwareVersion"),
        "Status": battery.get("Status", {}),
        # The payload carries no charge state; RemainingChargeTimeSeconds does not imply one.
        "ChargeState": None,
        "Oem": redpool_oem(
            "SmartStorageBattery",
            battery,
            {
                "ChargeLevelPercent": battery.get("ChargeLevelPercent"),
                "MaximumCapWatts": battery.get("MaximumCapWatts"),
                "RemainingChargeTimeSeconds": battery.get("RemainingChargeTimeSeconds"),
            },
        ),
    }
    return body


def fetch_hpe_storage_related(
    client: Any, system_id: str, storage_id: str
) -> Dict[str, Dict[str, Any]]:
    base = hpe_smartstorage_path(system_id, "ArrayControllers", storage_id)
    out = {
        "controller": redfish_get_json(client, base),
        "drives": redfish_get_json(client, f"{base}/DiskDrives"),
        "volumes": redfish_get_json(client, f"{base}/LogicalDrives"),
        "chassis": redfish_get_json(client, hpe_chassis_path(client, system_id)),
    }
    return out
