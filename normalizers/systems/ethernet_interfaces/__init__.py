# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register system ethernet interface normalizers into the central registry."""

from ...registry import (
    register_base,
    register_collection,
    register_collection_override,
    register_resource,
)
from .base import COLLECTION_MAPPING, BaseEthernetInterfaceNormalizer
from .dell import DellSystemEthernetInterfaceNormalizer
from .hpe import (
    HPE_COLLECTION_MAPPING,
    HPESystemEthernetInterfaceNormalizer,
    hpe_collection_prefetch,
)
from .intel import (
    INTEL_COLLECTION_MAPPING,
    IntelSystemEthernetInterfaceNormalizer,
    intel_collection_prefetch,
)

register_base("Systems/EthernetInterfaces", BaseEthernetInterfaceNormalizer())
_dell_eth = DellSystemEthernetInterfaceNormalizer()
register_resource("Systems/EthernetInterfaces", "Dell", _dell_eth)
register_resource(
    "Systems/EthernetInterfaces", "HPE", HPESystemEthernetInterfaceNormalizer()
)
register_resource(
    "Systems/EthernetInterfaces", "Intel", IntelSystemEthernetInterfaceNormalizer()
)
register_collection("Systems/EthernetInterfaces", COLLECTION_MAPPING)
register_collection_override(
    "Systems/EthernetInterfaces",
    "HPE",
    HPE_COLLECTION_MAPPING,
    prefetch=hpe_collection_prefetch,
)
register_collection_override(
    "Systems/EthernetInterfaces",
    "Intel",
    INTEL_COLLECTION_MAPPING,
    prefetch=intel_collection_prefetch,
)
