# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""A 48-bit MAC on a port means Ethernet; other address formats are not guessed."""

from __future__ import annotations

import logging

import pytest

from normalizers._shared.link_technology import ethernet_from_mac_address
from normalizers.chassis.network_adapters.hpe_chassis_network_rewrite import (
    _physical_to_port,
)
from normalizers.chassis.network_ports.base import (
    effective_network_port_active_link_technology,
)
from normalizers.types import NormalizationContext


@pytest.mark.parametrize(
    "mac",
    ["00:1B:44:AA:BB:CC", "00-1b-44-aa-bb-cc", "001B44AABBCC", " 00:1B:44:AA:BB:CC "],
)
def test_48_bit_mac_is_ethernet(mac: str) -> None:
    assert ethernet_from_mac_address(mac) == "Ethernet"


@pytest.mark.parametrize(
    "value",
    [
        "50:01:43:80:12:34:56:78",  # 64-bit WWN (Fibre Channel)
        "00:1B:44:AA:BB",  # too short
        "not-a-mac",
        "",
        None,
        12345,
    ],
)
def test_other_formats_are_not_ethernet(value: object) -> None:
    assert ethernet_from_mac_address(value) is None


def test_hpe_physical_port_with_mac_is_ethernet() -> None:
    out = _physical_to_port(
        {"Name": "Port 1", "MacAddress": "00:1B:44:AA:BB:CC"},
        "/redfish/v1/Chassis/1/NetworkAdapters/1/Ports/1",
        1,
    )
    assert out["LinkNetworkTechnology"] == "Ethernet"
    assert out["Ethernet"] == {"AssociatedMACAddresses": ["00:1B:44:AA:BB:CC"]}


def test_hpe_physical_port_without_mac_is_unknown() -> None:
    out = _physical_to_port({"Name": "Port 1"}, "/x/Ports/1", 1)
    assert "LinkNetworkTechnology" not in out
    assert out["@odata.type"] == "#Port.v1_20_0.Port"


def _ctx(data: dict) -> NormalizationContext:
    return NormalizationContext(data=data, client=None, logger=logging.getLogger("t"))


def test_base_port_reported_technology_wins_over_mac() -> None:
    ctx = _ctx(
        {"ActiveLinkTechnology": "FibreChannel", "MacAddress": "00:1B:44:AA:BB:CC"}
    )
    assert effective_network_port_active_link_technology(ctx) == "FibreChannel"


def test_base_port_uses_associated_address_when_no_mac_property() -> None:
    ctx = _ctx({"AssociatedNetworkAddresses": ["00:1B:44:AA:BB:CC"]})
    assert effective_network_port_active_link_technology(ctx) == "Ethernet"


def test_base_port_without_any_address_stays_unknown() -> None:
    assert effective_network_port_active_link_technology(_ctx({})) is None
