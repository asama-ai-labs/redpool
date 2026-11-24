# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register BootOption normalizers."""

from ...registry import register_base, register_collection
from .base import COLLECTION_MAPPING, BaseBootOptionNormalizer

register_base("Systems/BootOptions", BaseBootOptionNormalizer())
register_collection("Systems/BootOptions", COLLECTION_MAPPING)
