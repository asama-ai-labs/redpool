# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Supermicro NetworkProtocol: EngineId octets are space-separated."""

from __future__ import annotations

import copy
from typing import Any, Dict

from ...types import NormalizationContext
from .base import BaseNetworkProtocolNormalizer


def _enterprise_id_octets(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    compact = value.replace(" ", "").strip()
    if len(compact) != 8 or any(c not in "0123456789abcdefABCDEF" for c in compact):
        return value
    return " ".join(compact[i : i + 2] for i in range(0, 8, 2))


def _supermicro_snmp(ctx: NormalizationContext) -> Any:
    snmp = ctx.data.get("SNMP")
    if not isinstance(snmp, dict):
        return snmp if snmp is not None else {}
    out = copy.deepcopy(snmp)
    engine = out.get("EngineId")
    if isinstance(engine, dict) and "PrivateEnterpriseId" in engine:
        engine["PrivateEnterpriseId"] = _enterprise_id_octets(
            engine.get("PrivateEnterpriseId")
        )
    return out


class SupermicroNetworkProtocolNormalizer(BaseNetworkProtocolNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["SNMP"] = _supermicro_snmp
        return mapping
