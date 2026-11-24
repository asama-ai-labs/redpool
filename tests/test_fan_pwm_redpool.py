# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Non-schema fan PWM is copied to Oem.Redpool and omitted when absent."""

from __future__ import annotations

import logging

from normalizers.chassis.environment_metrics.base import (
    BaseEnvironmentMetricsNormalizer,
)
from normalizers.chassis.fans.base import BaseFanNormalizer
from normalizers.evaluator import evaluate
from normalizers.types import NormalizationContext


def _ctx(data: dict) -> NormalizationContext:
    return NormalizationContext(
        data=data,
        client=None,
        logger=logging.getLogger("test"),
    )


def test_environment_metrics_omits_redpool_when_pwm_absent() -> None:
    body = evaluate(BaseEnvironmentMetricsNormalizer().field_map(), _ctx({}))
    assert "Redpool" not in body["Oem"]


def test_fan_moves_dell_fan_pwm_into_redpool() -> None:
    body = evaluate(
        BaseFanNormalizer().field_map(),
        _ctx(
            {
                "Id": "Fan.Embedded.1A",
                "Oem": {"Dell": {"FanPWM": 15, "FanType": "Standard"}},
            }
        ),
    )
    assert body["Oem"]["Dell"]["FanPWM"] == 15
    assert body["Oem"]["Redpool"]["FanPWM"] == 15
