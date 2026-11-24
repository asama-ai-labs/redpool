# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo copies a real OEM power peak to SetPoint; 0xFFFF and 0 mean "not reported"."""

from __future__ import annotations

import logging
from typing import Any, Dict

from normalizers.evaluator import evaluate
from normalizers.systems.processors.environment_metrics.base import (
    BaseProcessorEnvironmentMetricsNormalizer,
)
from normalizers.systems.processors.environment_metrics.lenovo import (
    LenovoProcessorEnvironmentMetricsNormalizer,
)
from normalizers.types import NormalizationContext

EXCERPT: Dict[str, Any] = {
    "DataSourceUri": "/redfish/v1/Chassis/1/Controls/CPU1_PowerLimit",
    "Reading": None,
}


def _ctx(peak: Any, with_excerpt: bool = True) -> NormalizationContext:
    data: Dict[str, Any] = {
        "@odata.id": "/redfish/v1/Systems/1/Processors/1/EnvironmentMetrics",
        "Id": "EnvironmentMetrics",
        "Name": "EnvironmentMetrics",
    }
    if with_excerpt:
        data["PowerLimitWatts"] = dict(EXCERPT)
    parent = {"Id": "1", "Oem": {"Lenovo": {"PowerPeakLimitValue": peak}}}
    return NormalizationContext(
        data=data,
        client=None,
        logger=logging.getLogger("t"),
        prefetched={"_parent_processor": parent},
        vendor="Lenovo",
    )


def _lenovo(ctx: NormalizationContext) -> Dict[str, Any]:
    return evaluate(LenovoProcessorEnvironmentMetricsNormalizer().field_map(), ctx)


def test_real_peak_becomes_setpoint() -> None:
    assert _lenovo(_ctx(350))["PowerLimitWatts"] == {**EXCERPT, "SetPoint": 350}


def test_0xffff_is_not_published() -> None:
    assert _lenovo(_ctx(65535))["PowerLimitWatts"] == EXCERPT


def test_zero_is_not_published() -> None:
    assert _lenovo(_ctx(0))["PowerLimitWatts"] == EXCERPT


def test_0xffff_without_an_excerpt_omits_the_property() -> None:
    assert "PowerLimitWatts" not in _lenovo(_ctx(65535, with_excerpt=False))


def test_base_does_not_read_the_parent_oem_block() -> None:
    body = evaluate(BaseProcessorEnvironmentMetricsNormalizer().field_map(), _ctx(350))
    assert body["PowerLimitWatts"] == EXCERPT
