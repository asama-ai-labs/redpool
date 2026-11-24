# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo Chassis NetworkAdapter Port: vendor fields on the ``Port`` document."""

from __future__ import annotations

from typing import Any, Dict

from ...optional import OMIT, omit_if_null
from ...types import NormalizationContext
from ..network_ports.base import port_ethernet, port_link_status
from ..network_ports.lenovo import (
    effective_lenovo_network_port_associated_network_addresses,
    effective_lenovo_network_port_physical_port_number,
    prefetch_lenovo_network_port_ndf_mac,
)
from .base import BasePortNormalizer


def _lenovo_port_id(ctx: NormalizationContext) -> Any:
    port_id = ctx.data.get("PortId")
    if isinstance(port_id, str) and port_id.strip():
        return port_id.strip()
    number = effective_lenovo_network_port_physical_port_number(ctx)
    if isinstance(number, str) and number.strip():
        return number.strip()
    if isinstance(number, (int, float)) and not isinstance(number, bool):
        return str(int(number))
    return OMIT


def _lenovo_port_ethernet(ctx: NormalizationContext) -> Any:
    return port_ethernet(
        ctx, effective_lenovo_network_port_associated_network_addresses(ctx)
    )


class LenovoChassisPortNormalizer(BasePortNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_lenovo_network_port_ndf_mac(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["PortId"] = _lenovo_port_id
        m["Ethernet"] = _lenovo_port_ethernet
        m["LinkStatus"] = omit_if_null(port_link_status)
        return m
