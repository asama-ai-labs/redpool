# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Shared LogService and LogEntry normalizers.

The same schemas appear under both Systems/{id}/LogServices and
Managers/{id}/LogServices.  Define once, register under both paths.
"""

from __future__ import annotations

from typing import Any, Dict

from ..base import ResourceNormalizer
from ..optional import optional
from .log_entry.base import BaseLogEntryNormalizer  # noqa: F401 — re-export for callers
from .log_entry.v161 import canonicalize_sensor_type, stamp_log_entry_type
from .redfish_dates import date_time_or_none


class BaseLogServiceNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#LogService.LogService",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#LogService.v1_4_0.LogService",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "DateTime": optional("DateTime"),
            "DateTimeLocalOffset": optional("DateTimeLocalOffset"),
            "Entries": lambda ctx: ctx.data.get("Entries", {}),
            "MaxNumberOfRecords": optional("MaxNumberOfRecords"),
            "OverWritePolicy": optional("OverWritePolicy"),
            "ServiceEnabled": optional("ServiceEnabled"),
            "LogEntryType": optional("LogEntryType"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


LOG_SERVICE_COLLECTION: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#LogServiceCollection.LogServiceCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#LogServiceCollection.LogServiceCollection",
    "Members": lambda ctx: (
        [] if ctx.data.get("Members") is None else ctx.data.get("Members")
    ),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": optional("Description"),
    "Name": lambda ctx: ctx.data.get("Name", "LogServiceCollection"),
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}


def log_entry_collection_members(ctx: Any) -> Any:
    members = ctx.data.get("Members")
    if members is None:
        return []
    if not isinstance(members, list):
        return members
    out = []
    for member in members:
        if not isinstance(member, dict):
            out.append(member)
            continue
        # A placeholder time (0000-00-00T00:00:00Z) is unknown: omit it rather than send it.
        member = {
            key: value
            for key, value in member.items()
            if not (key in ("Created", "Modified") and date_time_or_none(value) is None)
        }
        sensor_type = member.get("SensorType")
        mapped = canonicalize_sensor_type(sensor_type)
        expanded = any(key != "@odata.id" for key in member)
        needs_type = expanded and not member.get("@odata.type")
        if mapped == sensor_type and not needs_type:
            out.append(member)
            continue
        member = dict(member)
        if mapped != sensor_type:
            member["SensorType"] = mapped
        if needs_type:
            stamp_log_entry_type(member)
        out.append(member)
    return out


LOG_ENTRY_COLLECTION: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#LogEntryCollection.LogEntryCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#LogEntryCollection.LogEntryCollection",
    "Members": log_entry_collection_members,
    "Members@odata.count": optional("Members@odata.count"),
    "Description": optional("Description"),
    "Name": lambda ctx: ctx.data.get("Name", "LogEntryCollection"),
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
