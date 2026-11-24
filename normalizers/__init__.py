# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Redpool normalizers — two-phase Redfish response normalization.

Public API is re-exported here for convenience. Importing this package
also triggers registration of all resource modules (systems, chassis,
managers, firmware_inventory).
"""

# Trigger registration of all resource modules.
from . import (
    chassis,  # noqa: F401, E402
    firmware_inventory,  # noqa: F401, E402
    managers,  # noqa: F401, E402
    systems,  # noqa: F401, E402
)
from .evaluator import evaluate  # noqa: F401
from .registry import (  # noqa: F401
    CollectionMapping,
    NormalizerEntry,
    get_collection_mapping,
    get_resource_entry,
    register_base,
    register_collection,
    register_collection_override,
    register_resource,
)
from .types import NormalizationContext  # noqa: F401
