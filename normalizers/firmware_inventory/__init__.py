# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register FirmwareInventory + SoftwareInventory normalizers.

Both use the SoftwareInventory schema; they are separate collections under
UpdateService but share the same normalizer.
"""

from ..registry import (
    register_base,
    register_collection,
    register_collection_override,
    register_resource,
)
from .base import COLLECTION_MAPPING, BaseSoftwareInventoryNormalizer
from .dell import DELL_COLLECTION_MAPPING, DellFirmwareInventoryNormalizer
from .hpe import HPEFirmwareInventoryNormalizer
from .lenovo import LenovoFirmwareInventoryNormalizer
from .supermicro import SupermicroFirmwareInventoryNormalizer

_PATH = "UpdateService/FirmwareInventory"
_BASE = BaseSoftwareInventoryNormalizer()

register_base(_PATH, _BASE)
register_resource(_PATH, "Lenovo", LenovoFirmwareInventoryNormalizer())
register_resource(_PATH, "Dell", DellFirmwareInventoryNormalizer())
register_resource(_PATH, "HPE", HPEFirmwareInventoryNormalizer())
register_resource(_PATH, "Supermicro", SupermicroFirmwareInventoryNormalizer())
register_collection(_PATH, COLLECTION_MAPPING)
register_collection_override(_PATH, "Dell", DELL_COLLECTION_MAPPING)

# Legacy short pattern (if resolved elsewhere).
register_base("FirmwareInventory", _BASE)
register_resource("FirmwareInventory", "Lenovo", LenovoFirmwareInventoryNormalizer())
register_resource("FirmwareInventory", "Dell", DellFirmwareInventoryNormalizer())
register_resource("FirmwareInventory", "HPE", HPEFirmwareInventoryNormalizer())
register_resource(
    "FirmwareInventory", "Supermicro", SupermicroFirmwareInventoryNormalizer()
)
register_collection("FirmwareInventory", COLLECTION_MAPPING)
register_collection_override("FirmwareInventory", "Dell", DELL_COLLECTION_MAPPING)

register_base("SoftwareInventory", _BASE)
register_resource("SoftwareInventory", "Lenovo", LenovoFirmwareInventoryNormalizer())
register_resource("SoftwareInventory", "Dell", DellFirmwareInventoryNormalizer())
register_resource("SoftwareInventory", "HPE", HPEFirmwareInventoryNormalizer())
register_resource(
    "SoftwareInventory", "Supermicro", SupermicroFirmwareInventoryNormalizer()
)
register_collection("SoftwareInventory", COLLECTION_MAPPING)
register_collection_override("SoftwareInventory", "Dell", DELL_COLLECTION_MAPPING)
