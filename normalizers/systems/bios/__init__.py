# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Bios normalizer (singleton under Systems/{id})."""

from ...registry import register_base, register_resource
from .base import BaseBiosNormalizer
from .intel import IntelBiosNormalizer
from .supermicro import SupermicroBiosNormalizer

register_base("Systems/Bios", BaseBiosNormalizer())
register_resource("Systems/Bios", "Intel", IntelBiosNormalizer())
register_resource("Systems/Bios", "Supermicro", SupermicroBiosNormalizer())
