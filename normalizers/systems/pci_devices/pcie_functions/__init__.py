# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register PCIeFunction normalizers (nested under Systems/PCIDevices)."""

from ....registry import register_base, register_collection
from .base import COLLECTION_MAPPING, BaseSystemsPCIeFunctionNormalizer

register_base("Systems/PCIDevices/PCIeFunctions", BaseSystemsPCIeFunctionNormalizer())
register_collection("Systems/PCIDevices/PCIeFunctions", COLLECTION_MAPPING)

register_base("Systems/PCIeDevices/PCIeFunctions", BaseSystemsPCIeFunctionNormalizer())
register_collection("Systems/PCIeDevices/PCIeFunctions", COLLECTION_MAPPING)

# Some vendors expose PCIeFunction as a peer collection under Systems (e.g. /redfish/v1/Systems/1/PCIeFunction).
register_base("Systems/PCIeFunction", BaseSystemsPCIeFunctionNormalizer())
register_collection("Systems/PCIeFunction", COLLECTION_MAPPING)
