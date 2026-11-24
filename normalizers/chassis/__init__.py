# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register chassis normalizers into the central registry."""

from ..registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseChassisNormalizer
from .dell import DellChassisNormalizer
from .intel import IntelChassisNormalizer
from .lenovo import LenovoChassisNormalizer
from .supermicro import SupermicroChassisNormalizer

register_base("Chassis", BaseChassisNormalizer())
register_resource("Chassis", "Dell", DellChassisNormalizer())
register_resource("Chassis", "Intel", IntelChassisNormalizer())
register_resource("Chassis", "Lenovo", LenovoChassisNormalizer())
register_resource("Chassis", "Supermicro", SupermicroChassisNormalizer())
register_collection("Chassis", COLLECTION_MAPPING)

from . import (  # noqa: E402
    assembly,  # noqa: F401
    drives,  # noqa: F401
    environment_metrics,  # noqa: F401
    fans,  # noqa: F401
    network_adapters,  # noqa: F401
    network_ports,  # noqa: F401
    pcie_devices,  # noqa: F401
    pcie_functions,  # noqa: F401
    pcie_slots,  # noqa: F401
    power,  # noqa: F401
    ports,  # noqa: F401
    power_supplies,  # noqa: F401
    power_supply_metrics,  # noqa: F401
    sensors,  # noqa: F401
    thermal,  # noqa: F401
)
