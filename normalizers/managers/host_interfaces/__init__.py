# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register HostInterface normalizers."""

from ...registry import register_base, register_collection
from .base import COLLECTION_MAPPING, BaseHostInterfaceNormalizer

register_base("Managers/HostInterfaces", BaseHostInterfaceNormalizer())
register_collection("Managers/HostInterfaces", COLLECTION_MAPPING)
