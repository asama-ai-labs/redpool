# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register VirtualMedia normalizers."""

from ...registry import register_base, register_collection
from .base import COLLECTION_MAPPING, BaseVirtualMediaNormalizer

register_base("Managers/VirtualMedia", BaseVirtualMediaNormalizer())
register_collection("Managers/VirtualMedia", COLLECTION_MAPPING)
