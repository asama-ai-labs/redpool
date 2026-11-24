# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Processor EnvironmentMetrics does not invent PowerLimitWatts.

OEM peak values copied onto SetPoint are checked by the normalized fixtures.
Schema validation rejects a PowerLimitWatts object with the wrong shape.
"""

from __future__ import annotations

from typing import Any, Dict

from normalizers.evaluator import evaluate
from normalizers.systems.processors.environment_metrics.base import (
    BaseProcessorEnvironmentMetricsNormalizer,
)
from normalizers.types import NormalizationContext


class _FakeLogger:
    def error(self, *args: object, **kwargs: object) -> None:
        pass


def test_existing_excerpt_is_kept_when_processor_has_no_peak() -> None:
    excerpt: Dict[str, Any] = {
        "DataSourceUri": "/redfish/v1/Chassis/1/Controls/CPU1_PowerLimit",
        "Reading": None,
    }
    ctx = NormalizationContext(
        data={
            "@odata.id": "/redfish/v1/Systems/1/Processors/1/EnvironmentMetrics",
            "Id": "EnvironmentMetrics",
            "Name": "EnvironmentMetrics",
            "PowerLimitWatts": excerpt,
        },
        client=None,
        logger=_FakeLogger(),
        prefetched={"_parent_processor": {"Id": "1", "Oem": {"Lenovo": {}}}},
    )
    body = evaluate(BaseProcessorEnvironmentMetricsNormalizer().field_map(), ctx)
    assert body["PowerLimitWatts"] == excerpt


def test_power_limit_omitted_when_absent() -> None:
    ctx = NormalizationContext(
        data={
            "@odata.id": "/redfish/v1/Systems/1/Processors/1/EnvironmentMetrics",
            "Id": "EnvironmentMetrics",
            "Name": "EnvironmentMetrics",
        },
        client=None,
        logger=_FakeLogger(),
    )
    body = evaluate(BaseProcessorEnvironmentMetricsNormalizer().field_map(), ctx)
    assert "PowerLimitWatts" not in body
