# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register MemoryMetrics normalizer (singleton under Memory/{id})."""

from ....registry import register_base, register_resource
from .base import BaseMemoryMetricsNormalizer
from .supermicro import SupermicroMemoryMetricsNormalizer

register_base("Systems/Memory/MemoryMetrics", BaseMemoryMetricsNormalizer())
register_resource(
    "Systems/Memory/MemoryMetrics",
    "Supermicro",
    SupermicroMemoryMetricsNormalizer(),
)
