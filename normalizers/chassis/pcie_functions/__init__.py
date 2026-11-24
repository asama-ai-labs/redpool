# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register PCIeFunction normalizers (nested under PCIeDevices)."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BasePCIeFunctionNormalizer
from .hpe import HPEChassisPCIeFunctionNormalizer

register_base("Chassis/PCIeDevices/PCIeFunctions", BasePCIeFunctionNormalizer())
register_resource(
    "Chassis/PCIeDevices/PCIeFunctions",
    "HPE",
    HPEChassisPCIeFunctionNormalizer(),
)
register_collection("Chassis/PCIeDevices/PCIeFunctions", COLLECTION_MAPPING)
