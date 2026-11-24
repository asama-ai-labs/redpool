# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Register SecureBoot normalizer (singleton under Systems/{id})."""

from ...registry import register_base, register_resource
from .base import BaseSecureBootNormalizer
from .supermicro import SupermicroSecureBootNormalizer

register_base("Systems/SecureBoot", BaseSecureBootNormalizer())
register_resource("Systems/SecureBoot", "Supermicro", SupermicroSecureBootNormalizer())
