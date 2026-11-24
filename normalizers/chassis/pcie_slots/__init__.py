# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register PCIeSlots normalizer (singleton under Chassis/{id})."""

from ...registry import register_base
from .base import BasePCIeSlotsNormalizer

register_base("Chassis/PCIeSlots", BasePCIeSlotsNormalizer())
