# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Storage Controller normalizers."""

from ....registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseStorageControllerNormalizer
from .dell import DellStorageControllerNormalizer
from .hpe import HPEStorageControllerNormalizer

register_base("Systems/Storage/Controllers", BaseStorageControllerNormalizer())
register_resource(
    "Systems/Storage/Controllers", "Dell", DellStorageControllerNormalizer()
)
register_resource(
    "Systems/Storage/Controllers", "HPE", HPEStorageControllerNormalizer()
)
register_collection("Systems/Storage/Controllers", COLLECTION_MAPPING)
