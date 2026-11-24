# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Processor EnvironmentMetrics normalizer (singleton under Processors/{id})."""

from ....registry import register_base, register_resource
from .base import BaseProcessorEnvironmentMetricsNormalizer
from .lenovo import LenovoProcessorEnvironmentMetricsNormalizer

register_base(
    "Systems/Processors/EnvironmentMetrics",
    BaseProcessorEnvironmentMetricsNormalizer(),
)
register_resource(
    "Systems/Processors/EnvironmentMetrics",
    "Lenovo",
    LenovoProcessorEnvironmentMetricsNormalizer(),
)
