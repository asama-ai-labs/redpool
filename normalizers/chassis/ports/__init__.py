# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register Chassis NetworkAdapter Port normalizers (``Ports``, the non-deprecated collection)."""

from ...registry import register_base, register_collection, register_resource
from . import dell  # noqa: F401 — Dell NetworkPorts→Ports request rewrite
from .base import PORT_COLLECTION_MAPPING, BasePortNormalizer
from .dell import DellChassisPortNormalizer
from .hpe import HPEChassisPortNormalizer
from .lenovo import LenovoChassisPortNormalizer

register_base("Chassis/NetworkAdapters/Ports", BasePortNormalizer())
register_resource("Chassis/NetworkAdapters/Ports", "Dell", DellChassisPortNormalizer())
register_resource("Chassis/NetworkAdapters/Ports", "HPE", HPEChassisPortNormalizer())
register_resource(
    "Chassis/NetworkAdapters/Ports", "Lenovo", LenovoChassisPortNormalizer()
)
register_collection("Chassis/NetworkAdapters/Ports", PORT_COLLECTION_MAPPING)
