# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register SerialInterface normalizers."""

from ...registry import register_base, register_collection
from .base import COLLECTION_MAPPING, BaseSerialInterfaceNormalizer

register_base("Managers/SerialInterfaces", BaseSerialInterfaceNormalizer())
register_collection("Managers/SerialInterfaces", COLLECTION_MAPPING)
