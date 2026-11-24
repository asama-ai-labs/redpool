# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Power normalizer (singleton under Chassis/{id})."""

from ...registry import register_base, register_resource
from .base import BasePowerNormalizer
from .dell import DellPowerNormalizer
from .hpe import HPEPowerNormalizer
from .lenovo import LenovoPowerNormalizer
from .supermicro import SupermicroPowerNormalizer

register_base("Chassis/Power", BasePowerNormalizer())
register_resource("Chassis/Power", "Dell", DellPowerNormalizer())
register_resource("Chassis/Power", "HPE", HPEPowerNormalizer())
register_resource("Chassis/Power", "Lenovo", LenovoPowerNormalizer())
register_resource("Chassis/Power", "Supermicro", SupermicroPowerNormalizer())
