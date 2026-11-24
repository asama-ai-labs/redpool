# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE Chassis NetworkAdapter Port: vendor fields on the ``Port`` document."""

from __future__ import annotations

from typing import Any, Dict

from ...optional import OMIT
from ...types import NormalizationContext
from ..network_ports.base import port_ethernet
from ..network_ports.hpe import (
    effective_hpe_network_port_associated_network_addresses,
    effective_hpe_network_port_status,
    effective_hpe_physical_port_number,
    prefetch_hpe_network_port_ndf_mac,
    prefetch_hpe_network_port_status,
)
from .base import BasePortNormalizer


def _hpe_port_id(ctx: NormalizationContext) -> Any:
    port_id = ctx.data.get("PortId")
    if isinstance(port_id, str) and port_id.strip():
        return port_id.strip()
    number = effective_hpe_physical_port_number(ctx)
    if isinstance(number, str) and number.strip():
        return number.strip()
    if isinstance(number, (int, float)) and not isinstance(number, bool):
        return str(int(number))
    return OMIT


def _hpe_port_ethernet(ctx: NormalizationContext) -> Any:
    return port_ethernet(
        ctx, effective_hpe_network_port_associated_network_addresses(ctx)
    )


class HPEChassisPortNormalizer(BasePortNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_hpe_network_port_status(ctx)
        prefetch_hpe_network_port_ndf_mac(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Status"] = effective_hpe_network_port_status
        m["PortId"] = _hpe_port_id
        m["Ethernet"] = _hpe_port_ethernet
        return m
