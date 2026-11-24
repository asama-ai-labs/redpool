# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register PCIeDevice normalizers."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BasePCIeDeviceNormalizer
from .hpe import HPEChassisPCIeDeviceNormalizer
from .lenovo import LenovoChassisPCIeDeviceNormalizer

register_base("Chassis/PCIeDevices", BasePCIeDeviceNormalizer())
register_resource("Chassis/PCIeDevices", "HPE", HPEChassisPCIeDeviceNormalizer())
register_resource("Chassis/PCIeDevices", "Lenovo", LenovoChassisPCIeDeviceNormalizer())
register_collection("Chassis/PCIeDevices", COLLECTION_MAPPING)
