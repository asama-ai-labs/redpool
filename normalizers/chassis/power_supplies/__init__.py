# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register PowerSupply normalizers (new-Redfish PowerSubsystem model)."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BasePowerSupplyNormalizer
from .hpe import HPEPowerSupplyNormalizer

register_base("Chassis/PowerSupplies", BasePowerSupplyNormalizer())
register_resource("Chassis/PowerSupplies", "HPE", HPEPowerSupplyNormalizer())
register_collection("Chassis/PowerSupplies", COLLECTION_MAPPING)
