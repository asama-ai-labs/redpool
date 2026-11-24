# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register manager ethernet interface normalizers into the central registry."""

from ...registry import register_base, register_collection, register_resource
from .base import COLLECTION_MAPPING, BaseManagerEthernetNormalizer
from .intel import IntelManagerEthernetNormalizer

register_base("Managers/EthernetInterfaces", BaseManagerEthernetNormalizer())
register_resource(
    "Managers/EthernetInterfaces", "Intel", IntelManagerEthernetNormalizer()
)
register_collection("Managers/EthernetInterfaces", COLLECTION_MAPPING)
