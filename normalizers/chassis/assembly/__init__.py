# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Assembly normalizer (singleton under Chassis/{id})."""

from ...registry import register_base
from .base import BaseAssemblyNormalizer

register_base("Chassis/Assembly", BaseAssemblyNormalizer())
