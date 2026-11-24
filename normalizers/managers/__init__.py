# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register manager normalizers into the central registry."""

from ..registry import register_base, register_collection
from .base import COLLECTION_MAPPING, BaseManagerNormalizer

register_base("Managers", BaseManagerNormalizer())
register_collection("Managers", COLLECTION_MAPPING)

from . import (  # noqa: E402
    ethernet_interfaces,  # noqa: F401
    host_interfaces,  # noqa: F401
    log_services,  # noqa: F401
    network_protocol,  # noqa: F401
    serial_interfaces,  # noqa: F401
    virtual_media,  # noqa: F401
)
