# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Systems-level PCIeDevice normalizers.

Registered under both ``Systems/PCIDevices`` (HPE OEM path) and
``Systems/PCIeDevices`` (standard Redfish path) so the normalizer
resolves regardless of which URL the vendor uses.
"""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseSystemsPCIeDeviceNormalizer
from .hpe import HpeSystemsPCIeDeviceNormalizer

register_base("Systems/PCIDevices", BaseSystemsPCIeDeviceNormalizer())
register_collection("Systems/PCIDevices", COLLECTION_MAPPING)
register_resource("Systems/PCIDevices", "HPE", HpeSystemsPCIeDeviceNormalizer())

register_base("Systems/PCIeDevices", BaseSystemsPCIeDeviceNormalizer())
register_collection("Systems/PCIeDevices", COLLECTION_MAPPING)
register_resource("Systems/PCIeDevices", "HPE", HpeSystemsPCIeDeviceNormalizer())

from . import pcie_functions  # noqa: F401, E402
