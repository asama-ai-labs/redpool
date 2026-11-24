# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Volume normalizers."""

from ....registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseVolumeNormalizer
from .dell import DellVolumeNormalizer
from .hpe import HPEVolumeNormalizer

register_base("Systems/Storage/Volumes", BaseVolumeNormalizer())
register_collection("Systems/Storage/Volumes", COLLECTION_MAPPING)
register_resource("Systems/Storage/Volumes", "Dell", DellVolumeNormalizer())
register_resource("Systems/Storage/Volumes", "HPE", HPEVolumeNormalizer())
