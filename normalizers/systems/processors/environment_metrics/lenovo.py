# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo Processor EnvironmentMetrics.

Lenovo reports the processor's power peak on the parent processor, in
``Oem.Lenovo.PowerPeakLimitValue``. It is copied to ``PowerLimitWatts.SetPoint``. ``0`` and
``0xFFFF`` mean the limit is not reported, so neither is published.
"""

from __future__ import annotations

from typing import Any, Dict

from redpool.redfish_client import redfish_get_json

from ....types import NormalizationContext
from .base import (
    BaseProcessorEnvironmentMetricsNormalizer,
    _positive_number,
    power_limit_body,
)

_PARENT_PROCESSOR_KEY = "_parent_processor"
_NOT_REPORTED = 0xFFFF


def _parent_processor_path(odata_id: str) -> str:
    path = (odata_id or "").split("#", 1)[0].rstrip("/")
    suffix = "/EnvironmentMetrics"
    if path.endswith(suffix):
        return path[: -len(suffix)]
    return ""


def _lenovo_power_peak(processor: Dict[str, Any]) -> int | float | None:
    oem = processor.get("Oem")
    lenovo = oem.get("Lenovo") if isinstance(oem, dict) else None
    if not isinstance(lenovo, dict):
        return None
    peak = _positive_number(lenovo.get("PowerPeakLimitValue"))
    return None if peak == _NOT_REPORTED else peak


def prefetch_parent_processor(ctx: NormalizationContext) -> None:
    """Load the parent processor so its OEM power peak can be copied here."""
    ctx.prefetched.pop(_PARENT_PROCESSOR_KEY, None)
    if ctx.client is None:
        return
    parent = _parent_processor_path(ctx.odata_id) or _parent_processor_path(
        ctx.resource_path
    )
    if not parent:
        return
    body = redfish_get_json(ctx.client, parent)
    if isinstance(body, dict) and body:
        ctx.prefetched[_PARENT_PROCESSOR_KEY] = body


def lenovo_environment_power_limit(ctx: NormalizationContext) -> Any:
    parent = ctx.prefetched.get(_PARENT_PROCESSOR_KEY) if ctx.prefetched else None
    peak = _lenovo_power_peak(parent) if isinstance(parent, dict) else None
    return power_limit_body(ctx, peak)


class LenovoProcessorEnvironmentMetricsNormalizer(
    BaseProcessorEnvironmentMetricsNormalizer
):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_parent_processor(ctx)

    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["PowerLimitWatts"] = lenovo_environment_power_limit
        return mapping
