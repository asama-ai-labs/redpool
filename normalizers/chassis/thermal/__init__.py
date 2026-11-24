# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Thermal normalizer (singleton under Chassis/{id})."""

from ...registry import register_base, register_resource
from .base import BaseThermalNormalizer
from .supermicro import SupermicroThermalNormalizer

register_base("Chassis/Thermal", BaseThermalNormalizer())
register_resource("Chassis/Thermal", "Supermicro", SupermicroThermalNormalizer())
