# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Normalize LogEntry responses toward LogEntry.v1_16_1 shape.

Vendor-specific OEM promotion lives in ``normalizers._shared.log_entry`` subclasses;
this module holds shared build steps and redpool merge helpers.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ...types import NormalizationContext
from ..redfish_dates import date_time_or_none

if TYPE_CHECKING:
    from .base import BaseLogEntryNormalizer

LOG_ENTRY_CONTEXT = "/redfish/v1/$metadata#LogEntry.LogEntry"

# IPMI Table 42-3 names that Redfish spells differently. Values already in
# the LogEntry SensorType enum are left unchanged.
_SENSOR_TYPE_ALIASES = {
    "Power Supply": "Power Supply / Converter",
    "Power Unit": "PowerUnit",
    "Cooling Device": "CoolingDevice",
    "Drive Slot": "Drive Slot/Bay",
    "Drive Slot (Bay)": "Drive Slot/Bay",
    "Physical Security": "Physical Chassis Security",
    "Button / Switch": "Button/Switch",
    "Module / Board": "Module/Board",
    "Microcontroller / Coprocessor": "Microcontroller/Coprocessor",
    "Chip Set": "ChipSet",
    "Cable / Interconnect": "Cable/Interconnect",
    "System Boot Initiated": "SystemBoot/Restart",
    "System Boot / Restart": "SystemBoot/Restart",
    "Base OS Boot/Installation Status": "BaseOSBoot/InstallationStatus",
    "OS Stop / Shutdown": "OS Stop/Shutdown",
    "OS Critical Stop": "OS Stop/Shutdown",
    "Slot / Connector": "Slot/Connector",
    "System ACPI Power State": "System ACPI PowerState",
    "Monitor ASIC / IC": "Monitor ASIC/IC",
    "FRU State": "FRUState",
    "Watchdog1": "Watchdog",
    "Watchdog 1": "Watchdog",
    "Watchdog2": "Watchdog",
    "Watchdog 2": "Watchdog",
}


def canonicalize_sensor_type(value: Any) -> Any:
    """Map an IPMI sensor-type name onto the LogEntry SensorType enum."""
    if not isinstance(value, str):
        return value
    return _SENSOR_TYPE_ALIASES.get(value, value)


# Omit from Oem.Redpool — already represented as standard LogEntry properties (or deprecated OEM keys).
_REDP_SKIP_KEYS = frozenset(
    {
        "Id",
        "Name",
        "Severity",
        "Updated",
        "EventID",
        "EventID@Redfish.Deprecated",
    }
)

# Keys we may emit (sparse: only non-None / meaningful values, except required).
_PASS_THROUGH_KEYS: List[str] = [
    "@odata.etag",
    "Description",
    "Created",
    "Modified",
    "Severity",
    "Message",
    "MessageId",
    "MessageArgs",
    "EntryCode",
    "SensorType",
    "SensorNumber",
    "OemSensorType",
    "OemLogEntryCode",
    "EventType",
    "EventId",
    "EventTimestamp",
    "EventGroupId",
    "GeneratorId",
    "OemRecordFormat",
    "Originator",
    "OriginatorType",
    "Resolution",
    "Resolved",
    "ResolutionSteps",
    "SpecificEventExistsInGroup",
    "ServiceProviderNotified",
    "Persistency",
    "FirstOverflowTimestamp",
    "LastOverflowTimestamp",
    "OverflowErrorCount",
    "AdditionalDataURI",
    "AdditionalDataSizeBytes",
    "DiagnosticData",
    "DiagnosticDataType",
    "OEMDiagnosticDataType",
    "CPER",
    "CXLEntryType",
    "Links",
    "Actions",
    "RelatedItem",
    "RelatedItem@odata.count",
    "RelatedLogEntries",
    "RelatedLogEntries@odata.count",
]


def severity_hpe_to_redfish(sev: Optional[str]) -> Optional[str]:
    if sev is None or not isinstance(sev, str):
        return None
    s = sev.strip()
    mapping = {
        "OK": "OK",
        "Informational": "OK",
        "Repaired": "OK",
        "Cleared": "OK",
        "None": "OK",
        "Caution": "Warning",
        "Warning": "Warning",
        "Critical": "Critical",
    }
    return mapping.get(s)


def oem_branch_to_redpool_props(branch: Dict[str, Any]) -> Dict[str, Any]:
    """Copy vendor OEM object into flat redpool entries; keep original key names."""
    return {
        k: copy.deepcopy(v)
        for k, v in branch.items()
        if not k.startswith("@odata.") and k not in _REDP_SKIP_KEYS
    }


def stamp_log_entry_type(member: Dict[str, Any]) -> None:
    member["@odata.type"] = "#LogEntry.v1_16_1.LogEntry"


def build_log_entry_v161(
    ctx: NormalizationContext,
    normalizer: "BaseLogEntryNormalizer",
) -> Dict[str, Any]:
    d = ctx.data
    out: Dict[str, Any] = {
        "@odata.context": LOG_ENTRY_CONTEXT,
        "@odata.type": None,
        "@odata.id": d.get("@odata.id") or ctx.odata_id,
        "Id": d.get("Id"),
        "Name": d.get("Name"),
        "EntryType": d.get("EntryType"),
    }

    stamp_log_entry_type(out)

    for key in _PASS_THROUGH_KEYS:
        if key not in d:
            continue
        val = d[key]
        if key in ("Created", "Modified"):
            val = date_time_or_none(val)
        if val is not None:
            if key == "SensorType":
                val = canonicalize_sensor_type(val)
            out[key] = val
        elif key in ("SensorType", "SensorNumber", "Description", "Severity"):
            out[key] = val

    if d.get("@odata.etag") is not None:
        out["@odata.etag"] = d["@odata.etag"]

    msg_args = d.get("MessageArgs")
    if isinstance(msg_args, list):
        out["MessageArgs"] = msg_args
        out["MessageArgs@odata.count"] = len(msg_args)
    elif d.get("MessageArgs@odata.count") is not None:
        out["MessageArgs@odata.count"] = d["MessageArgs@odata.count"]

    if d.get("OemLogEntryCode") is not None:
        out["OemLogEntryCode"] = d["OemLogEntryCode"]
    if d.get("OemSensorType") is not None:
        out["OemSensorType"] = d["OemSensorType"]

    redpool: Dict[str, Any] = {}
    oem_src = d.get("Oem")
    oem_out: Dict[str, Any] = (
        copy.deepcopy(oem_src) if isinstance(oem_src, dict) else {}
    )

    normalizer.enrich_log_entry_oem(out, oem_out, redpool)

    if redpool:
        oem_out["Redpool"] = redpool

    if oem_out:
        out["Oem"] = oem_out

    return out


# Superset for callers that evaluate field_map without normalized_body_from_prefetch.
LOG_ENTRY_FIELD_MAP_KEYS: tuple[str, ...] = (
    "@odata.context",
    "@odata.type",
    "@odata.etag",
    "@odata.id",
    "Id",
    "Name",
    "Description",
    "Created",
    "Modified",
    "EntryType",
    "Severity",
    "Message",
    "MessageId",
    "MessageArgs",
    "MessageArgs@odata.count",
    "EntryCode",
    "SensorType",
    "SensorNumber",
    "OemSensorType",
    "OemLogEntryCode",
    "EventType",
    "EventId",
    "EventTimestamp",
    "EventGroupId",
    "GeneratorId",
    "OemRecordFormat",
    "Originator",
    "OriginatorType",
    "Resolution",
    "Resolved",
    "ResolutionSteps",
    "Links",
    "Actions",
    "Oem",
)
