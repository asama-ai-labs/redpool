# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register storage normalizers into the central registry."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseStorageNormalizer
from .dell import DellStorageNormalizer
from .hpe import HPEStorageNormalizer
from .intel import IntelStorageNormalizer

register_base("Systems/Storage", BaseStorageNormalizer())
register_resource("Systems/Storage", "Dell", DellStorageNormalizer())
register_resource("Systems/Storage", "HPE", HPEStorageNormalizer())
register_resource("Systems/Storage", "Intel", IntelStorageNormalizer())
register_collection("Systems/Storage", COLLECTION_MAPPING)

from . import (  # noqa: E402
    controllers,  # noqa: F401
    drives,  # noqa: F401
    volumes,  # noqa: F401
)
