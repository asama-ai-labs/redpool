# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register NetworkProtocol normalizer (singleton under Managers/{id})."""

from ...registry import register_base, register_resource
from .base import BaseNetworkProtocolNormalizer
from .supermicro import SupermicroNetworkProtocolNormalizer

register_base("Managers/NetworkProtocol", BaseNetworkProtocolNormalizer())
register_resource(
    "Managers/NetworkProtocol",
    "Supermicro",
    SupermicroNetworkProtocolNormalizer(),
)
