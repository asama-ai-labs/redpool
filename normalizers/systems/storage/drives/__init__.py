# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Storage Drive normalizers."""

from ....registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseStorageDriveNormalizer
from .dell import DellStorageDriveNormalizer
from .hpe import HPEStorageDriveNormalizer
from .intel import IntelStorageDriveNormalizer

register_base("Systems/Storage/Drives", BaseStorageDriveNormalizer())
register_resource("Systems/Storage/Drives", "Dell", DellStorageDriveNormalizer())
register_resource("Systems/Storage/Drives", "HPE", HPEStorageDriveNormalizer())
register_resource("Systems/Storage/Drives", "Intel", IntelStorageDriveNormalizer())
register_collection("Systems/Storage/Drives", COLLECTION_MAPPING)
