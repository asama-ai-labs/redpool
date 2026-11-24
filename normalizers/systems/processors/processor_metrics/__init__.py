# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register ProcessorMetrics normalizer (singleton under Processors/{id})."""

from ....registry import register_base
from .base import BaseProcessorMetricsNormalizer

register_base("Systems/Processors/ProcessorMetrics", BaseProcessorMetricsNormalizer())
