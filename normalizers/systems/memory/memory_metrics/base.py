# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base MemoryMetrics normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ....base import ResourceNormalizer
from ....optional import optional


class BaseMemoryMetricsNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#MemoryMetrics.MemoryMetrics",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#MemoryMetrics.v1_7_0.MemoryMetrics",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "BandwidthPercent": optional("BandwidthPercent"),
            "OperatingSpeedMHz": optional("OperatingSpeedMHz"),
            "HealthData": lambda ctx: ctx.data.get("HealthData", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }
