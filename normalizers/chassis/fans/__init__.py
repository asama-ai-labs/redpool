# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Fan normalizers (new-Redfish ThermalSubsystem model)."""

from ...registry import register_base, register_collection
from .base import COLLECTION_MAPPING, BaseFanNormalizer

register_base("Chassis/Fans", BaseFanNormalizer())
register_collection("Chassis/Fans", COLLECTION_MAPPING)
