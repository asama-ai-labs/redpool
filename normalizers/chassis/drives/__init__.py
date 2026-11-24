# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Chassis Drive normalizers."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseChassisDriveNormalizer
from .dell import DellChassisDriveNormalizer
from .supermicro import SupermicroChassisDriveNormalizer

register_base("Chassis/Drives", BaseChassisDriveNormalizer())
register_resource("Chassis/Drives", "Dell", DellChassisDriveNormalizer())
register_resource("Chassis/Drives", "Supermicro", SupermicroChassisDriveNormalizer())
register_collection("Chassis/Drives", COLLECTION_MAPPING)
