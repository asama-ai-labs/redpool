# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Chassis NetworkPort normalizers."""

from ...registry import register_base, register_collection, register_resource
from . import (
    lenovo_ports_rewrite,  # noqa: F401 — loads Lenovo NetworkPorts→Ports rewrite
)
from .base import COLLECTION_MAPPING, BaseNetworkPortNormalizer
from .dell import DellChassisNetworkPortNormalizer
from .hpe import (
    HPEChassisNetworkPortNormalizer,  # noqa: F401 — loads hpe_ports rewrite registration
)
from .lenovo import LenovoChassisNetworkPortNormalizer

register_base("Chassis/NetworkAdapters/NetworkPorts", BaseNetworkPortNormalizer())
_dell_np = DellChassisNetworkPortNormalizer()
register_resource("Chassis/NetworkAdapters/NetworkPorts", "Dell", _dell_np)
_hpe_np = HPEChassisNetworkPortNormalizer()
register_resource("Chassis/NetworkAdapters/NetworkPorts", "HPE", _hpe_np)
_lenovo_np = LenovoChassisNetworkPortNormalizer()
register_resource("Chassis/NetworkAdapters/NetworkPorts", "Lenovo", _lenovo_np)
register_collection("Chassis/NetworkAdapters/NetworkPorts", COLLECTION_MAPPING)
