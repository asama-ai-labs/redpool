# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register processor normalizers into the central registry."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseProcessorNormalizer
from .dell import DellProcessorNormalizer
from .hpe import HPEProcessorNormalizer
from .intel import IntelProcessorNormalizer
from .lenovo import LenovoProcessorNormalizer
from .supermicro import SupermicroProcessorNormalizer

register_base("Systems/Processors", BaseProcessorNormalizer())
register_resource("Systems/Processors", "Dell", DellProcessorNormalizer())
register_resource("Systems/Processors", "HPE", HPEProcessorNormalizer())
register_resource("Systems/Processors", "Intel", IntelProcessorNormalizer())
register_resource("Systems/Processors", "Lenovo", LenovoProcessorNormalizer())
register_resource("Systems/Processors", "Supermicro", SupermicroProcessorNormalizer())
register_collection("Systems/Processors", COLLECTION_MAPPING)

from . import environment_metrics, processor_metrics  # noqa: F401, E402
