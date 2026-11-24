# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register EnvironmentMetrics normalizer (singleton under Chassis/{id})."""

from ...registry import register_base
from .base import BaseEnvironmentMetricsNormalizer

register_base("Chassis/EnvironmentMetrics", BaseEnvironmentMetricsNormalizer())
