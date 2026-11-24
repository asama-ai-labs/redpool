# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base PowerSupply Metrics normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import optional


class BasePowerSupplyMetricsNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#PowerSupplyMetrics.PowerSupplyMetrics",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#PowerSupplyMetrics.v1_1_0.PowerSupplyMetrics",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "InputPowerWatts": optional("InputPowerWatts"),
            "OutputPowerWatts": optional("OutputPowerWatts"),
            "InputVoltage": optional("InputVoltage"),
            "InputCurrentAmps": optional("InputCurrentAmps"),
            "RailVoltage": lambda ctx: ctx.data.get("RailVoltage", []),
            "FrequencyHz": optional("FrequencyHz"),
            "TemperatureCelsius": optional("TemperatureCelsius"),
            "FanSpeedsPercent": lambda ctx: ctx.data.get("FanSpeedsPercent", []),
            "Status": lambda ctx: ctx.data.get("Status", {}),
        }
