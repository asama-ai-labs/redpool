# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register NetworkInterface normalizers."""

from ...registry import register_base, register_collection
from .base import COLLECTION_MAPPING, BaseNetworkInterfaceNormalizer

register_base("Systems/NetworkInterfaces", BaseNetworkInterfaceNormalizer())
register_collection("Systems/NetworkInterfaces", COLLECTION_MAPPING)
