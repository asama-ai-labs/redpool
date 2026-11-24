# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base ProcessorMetrics normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ....base import ResourceNormalizer
from ....optional import optional


class BaseProcessorMetricsNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#ProcessorMetrics.ProcessorMetrics",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#ProcessorMetrics.v1_6_0.ProcessorMetrics",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "OperatingSpeedMHz": optional("OperatingSpeedMHz"),
            "BandwidthPercent": optional("BandwidthPercent"),
            "AverageFrequencyMHz": optional("AverageFrequencyMHz"),
            "ThrottlingCelsius": optional("ThrottlingCelsius"),
            "TemperatureCelsius": optional("TemperatureCelsius"),
            "ConsumedPowerWatt": optional("ConsumedPowerWatt"),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }
