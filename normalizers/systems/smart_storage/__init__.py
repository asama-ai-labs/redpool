# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register HPE SmartStorage normalizers (ArrayControllers, DiskDrives, LogicalDrives).

Path resolution only includes collection segments, so .../SmartStorage/ArrayControllers
resolves to pattern Systems/ArrayControllers (SmartStorage is a resource, not a collection).
We register under both patterns so that either resolution matches.
"""

from ...registry import register_base, register_collection
from .array_controllers.base import (
    COLLECTION_MAPPING as ARRAY_COLLECTION_MAPPING,
)
from .array_controllers.base import (
    BaseSmartStorageArrayControllerNormalizer,
)
from .disk_drives.base import (
    COLLECTION_MAPPING as DISK_DRIVES_COLLECTION_MAPPING,
)
from .disk_drives.base import (
    BaseSmartStorageDiskDriveNormalizer,
)
from .logical_drives.base import (
    COLLECTION_MAPPING as LOGICAL_DRIVES_COLLECTION_MAPPING,
)
from .logical_drives.base import (
    BaseSmartStorageLogicalDriveNormalizer,
)

# Pattern as resolved by proxy: Systems/ArrayControllers (SmartStorage is intermediate resource)
register_base("Systems/ArrayControllers", BaseSmartStorageArrayControllerNormalizer())
register_collection("Systems/ArrayControllers", ARRAY_COLLECTION_MAPPING)

register_base(
    "Systems/ArrayControllers/DiskDrives",
    BaseSmartStorageDiskDriveNormalizer(),
)
register_collection(
    "Systems/ArrayControllers/DiskDrives",
    DISK_DRIVES_COLLECTION_MAPPING,
)

register_base(
    "Systems/ArrayControllers/LogicalDrives",
    BaseSmartStorageLogicalDriveNormalizer(),
)
register_collection(
    "Systems/ArrayControllers/LogicalDrives",
    LOGICAL_DRIVES_COLLECTION_MAPPING,
)
