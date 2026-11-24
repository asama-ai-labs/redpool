# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo Chassis Sensor.

``RelatedItem`` is kept. Sensors are not marked for export skipping. A client
that only reads ``Chassis/Sensors`` still sees every member, including readings
that also appear on Thermal, Power, or Processors.
"""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseSensorNormalizer


class LenovoChassisSensorNormalizer(BaseSensorNormalizer):
    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["RelatedItem"] = lambda ctx: ctx.data.get("RelatedItem", [])
        return m
