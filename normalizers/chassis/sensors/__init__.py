# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Sensor normalizers."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseSensorNormalizer
from .lenovo import LenovoChassisSensorNormalizer

register_base("Chassis/Sensors", BaseSensorNormalizer())
register_resource("Chassis/Sensors", "Lenovo", LenovoChassisSensorNormalizer())
register_collection("Chassis/Sensors", COLLECTION_MAPPING)
