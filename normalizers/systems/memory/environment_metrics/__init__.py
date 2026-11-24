# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Memory EnvironmentMetrics normalizer (singleton under Memory/{id})."""

from ....registry import register_base
from .base import BaseMemoryEnvironmentMetricsNormalizer

register_base(
    "Systems/Memory/EnvironmentMetrics", BaseMemoryEnvironmentMetricsNormalizer()
)
