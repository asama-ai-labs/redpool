# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Processor EnvironmentMetrics.

``PowerLimitWatts.SetPoint`` is the standard property's own value. A BMC that reports a
power limit somewhere else (Lenovo, on the parent processor's OEM block) is handled in
that vendor's module.
"""

from __future__ import annotations

from typing import Any, Dict

from ....base import ResourceNormalizer
from ....optional import OMIT, optional
from ....types import NormalizationContext


def _positive_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value > 0:
        return value
    return None


def _setpoint_from_environment_metrics(doc: Dict[str, Any]) -> int | float | None:
    raw = doc.get("PowerLimitWatts")
    if isinstance(raw, dict):
        return _positive_number(raw.get("SetPoint"))
    return _positive_number(raw)


def power_limit_body(ctx: NormalizationContext, setpoint: int | float | None) -> Any:
    """``EnvironmentMetrics.PowerLimitWatts`` carrying *setpoint*, or the payload's own value."""
    existing = ctx.data.get("PowerLimitWatts")
    if setpoint is None:
        setpoint = _setpoint_from_environment_metrics(ctx.data)
    if setpoint is None:
        return OMIT if existing is None else existing
    body = dict(existing) if isinstance(existing, dict) else {}
    body["SetPoint"] = setpoint
    return body


def processor_environment_power_limit(ctx: NormalizationContext) -> Any:
    return power_limit_body(ctx, None)


class BaseProcessorEnvironmentMetricsNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#EnvironmentMetrics.EnvironmentMetrics",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#EnvironmentMetrics.v1_3_0.EnvironmentMetrics",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "TemperatureCelsius": optional("TemperatureCelsius"),
            "PowerWatts": optional("PowerWatts"),
            "FanSpeedsPercent": optional("FanSpeedsPercent"),
            "PowerLimitWatts": processor_environment_power_limit,
        }
