# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Sensor normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BaseSensorNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Sensor.Sensor",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Sensor.v1_9_0.Sensor",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "Reading": optional("Reading"),
            "ReadingType": optional("ReadingType"),
            "ReadingUnits": optional("ReadingUnits"),
            "ReadingRangeMin": optional("ReadingRangeMin"),
            "ReadingRangeMax": optional("ReadingRangeMax"),
            "Precision": optional("Precision"),
            "PhysicalContext": optional("PhysicalContext"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Thresholds": lambda ctx: ctx.data.get("Thresholds", {}),
            "MinAllowableOperatingValue": optional("MinAllowableOperatingValue"),
            "MaxAllowableOperatingValue": optional("MaxAllowableOperatingValue"),
            "SpeedRPM": optional("SpeedRPM"),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#SensorCollection.SensorCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#SensorCollection.SensorCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Sensors",
    "Name": "SensorCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
