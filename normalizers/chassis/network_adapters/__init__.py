# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register NetworkAdapter normalizers."""

from ...registry import register_base, register_collection, register_resource
from . import (
    hpe_chassis_network_rewrite,  # noqa: F401 — HPE Chassis↔BaseNetworkAdapter rewrite
)
from .base import COLLECTION_MAPPING, BaseNetworkAdapterNormalizer
from .dell import DellChassisNetworkAdapterNormalizer
from .hpe import HPEChassisNetworkAdapterNormalizer
from .lenovo import LenovoChassisNetworkAdapterNormalizer

register_base("Chassis/NetworkAdapters", BaseNetworkAdapterNormalizer())
_dell_na = DellChassisNetworkAdapterNormalizer()
register_resource("Chassis/NetworkAdapters", "Dell", _dell_na)
_hpe_na = HPEChassisNetworkAdapterNormalizer()
register_resource("Chassis/NetworkAdapters", "HPE", _hpe_na)
_lnv_na = LenovoChassisNetworkAdapterNormalizer()
register_resource("Chassis/NetworkAdapters", "Lenovo", _lnv_na)
register_collection("Chassis/NetworkAdapters", COLLECTION_MAPPING)
