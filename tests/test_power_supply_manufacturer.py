# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""PowerSupply manufacturer when the PSU omits it: never the server vendor.

Alias expansion for captured PSUs is in the normalized fixtures.
"""

from __future__ import annotations

import logging

import pytest

from normalizers.chassis.power.dell import _normalize_power_supplies_dell
from normalizers.chassis.power_supplies.base import _power_supply_manufacturer
from normalizers.types import NormalizationContext
from normalizers.vendor_id import normalize_power_supply_manufacturer


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GREA", "Great Wall Power Technology Company Limited"),
        ("lton", "Lite-On Technology Corporation"),
    ],
)
def test_power_supply_manufacturer_aliases(raw: str, expected: str) -> None:
    assert normalize_power_supply_manufacturer(raw) == expected


def test_manufacturer_is_not_the_server_vendor() -> None:
    # An HPE server's PSU may be made by anyone; the server vendor is not its maker.
    ctx = NormalizationContext(
        data={"Manufacturer": ""},
        client=None,
        logger=logging.getLogger("test"),
        vendor="HPE",
    )
    assert _power_supply_manufacturer(ctx) is None


def test_manufacturer_empty_when_no_vendor() -> None:
    ctx = NormalizationContext(
        data={"Manufacturer": ""},
        client=None,
        logger=logging.getLogger("test"),
        vendor="",
    )
    assert _power_supply_manufacturer(ctx) is None


def test_dell_psu_manufacturer_from_model_tail() -> None:
    ctx = NormalizationContext(
        data={
            "PowerSupplies": [
                {
                    "Manufacturer": "DELL",
                    "Model": "PWR SPLY,1600W,RDNT,DELTA",
                    "MemberId": "0",
                    "Status": {},
                },
            ]
        },
        client=None,
        logger=logging.getLogger("test"),
        vendor="Dell",
    )
    out = _normalize_power_supplies_dell(ctx)
    assert out[0]["Manufacturer"] == "Delta Electronics, Inc."
