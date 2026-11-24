# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register memory normalizers into the central registry."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseMemoryNormalizer
from .dell_memory import DellMemoryNormalizer
from .hpe_memory import HPEMemoryNormalizer
from .intel import IntelMemoryNormalizer
from .lenovo_memory import LenovoMemoryNormalizer

register_base("Systems/Memory", BaseMemoryNormalizer())
register_resource("Systems/Memory", "Dell", DellMemoryNormalizer())
register_resource("Systems/Memory", "HPE", HPEMemoryNormalizer())
register_resource("Systems/Memory", "Intel", IntelMemoryNormalizer())
register_resource("Systems/Memory", "Lenovo", LenovoMemoryNormalizer())
register_collection("Systems/Memory", COLLECTION_MAPPING)

from . import (  # noqa: E402
    environment_metrics,  # noqa: F401
    memory_metrics,  # noqa: F401
)
