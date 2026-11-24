# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register ComputerSystem normalizers into the central registry."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseComputerSystemNormalizer
from .dell import DellComputerSystemNormalizer
from .hpe import HPEComputerSystemNormalizer
from .lenovo import LenovoComputerSystemNormalizer

register_base("Systems", BaseComputerSystemNormalizer())
register_resource("Systems", "Dell", DellComputerSystemNormalizer())
register_resource("Systems", "HPE", HPEComputerSystemNormalizer())
register_resource("Systems", "Lenovo", LenovoComputerSystemNormalizer())
register_collection("Systems", COLLECTION_MAPPING)
