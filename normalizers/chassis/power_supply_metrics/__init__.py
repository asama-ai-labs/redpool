# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register PowerSupply Metrics normalizer (singleton under PowerSupplies/{id})."""

from ...registry import register_base
from .base import BasePowerSupplyMetricsNormalizer

register_base("Chassis/PowerSupplies/Metrics", BasePowerSupplyMetricsNormalizer())
