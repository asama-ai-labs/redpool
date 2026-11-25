# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register PCIeSlots normalizer (singleton under Chassis/{id})."""

from ...registry import register_base, register_resource
from .base import BasePCIeSlotsNormalizer
from .hpe import HPEPCIeSlotsNormalizer

register_base("Chassis/PCIeSlots", BasePCIeSlotsNormalizer())
register_resource("Chassis/PCIeSlots", "HPE", HPEPCIeSlotsNormalizer())
