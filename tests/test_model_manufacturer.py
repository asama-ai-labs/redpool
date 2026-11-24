# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""A model name's product line can name the maker: "HPE Smart Array", "BP14G+ 0:1"."""

from __future__ import annotations

import logging

import pytest

from normalizers.chassis.base import _effective_chassis_manufacturer
from normalizers.systems.storage._hpe_smartstorage import (
    build_storage_controller_resource,
)
from normalizers.types import NormalizationContext
from normalizers.vendor_id import manufacturer_from_model


@pytest.mark.parametrize(
    ("model", "maker"),
    [
        ("HPE Smart Array E208i-a SR Gen10", "HPE"),
        ("HPE Smart Storage Battery", "HPE"),
        ("ProLiant DL380 Gen10", "HPE"),
        ("MSA 2050", "HPE"),
        ("PowerEdge R640", "Dell Inc."),
        ("PERC H730P Mini", "Dell Inc."),
        ("BP14G+ 0:1", "Dell Inc."),
        ("BP14G+EXP 0:1", "Dell Inc."),
        ("BP_PSV 0:1", "Dell Inc."),
        ("BPN-SAS3-LB16A-N10", "Supermicro"),
        ("ThinkSystem SR630 V2", "Lenovo"),
        ("SYS-220TP-HTTR", "Supermicro"),
    ],
)
def test_product_line_names_the_maker(model: str, maker: str) -> None:
    assert manufacturer_from_model(model) == maker


@pytest.mark.parametrize(
    "model",
    [
        "PCIe SSD Backplane 1",  # no maker in the name
        "PWR SPLY,1600W,RDNT,DELTA",  # PSU: handled by the PSU alias table
        "875241-B21",  # bare part number
        "Cascade Lake Xeon",  # not a product-line token we own
        "",
        None,
    ],
)
def test_no_maker_named_means_none(model: str | None) -> None:
    assert manufacturer_from_model(model) is None


def test_enclosure_takes_the_maker_from_its_backplane_model() -> None:
    ctx = NormalizationContext(
        data={
            "ChassisType": "StorageEnclosure",
            "Model": "BP14G+ 0:1",
            "Manufacturer": "",
        },
        client=None,
        logger=logging.getLogger("test"),
        vendor="HPE",
    )
    assert _effective_chassis_manufacturer(ctx) == "Dell Inc."


def test_model_named_maker_beats_the_vendor_fallback() -> None:
    ctx = NormalizationContext(
        data={
            "ChassisType": "RackMount",
            "Model": "PowerEdge R640",
            "Manufacturer": "",
        },
        client=None,
        logger=logging.getLogger("test"),
        vendor="HPE",
    )
    assert _effective_chassis_manufacturer(ctx) == "Dell Inc."


def test_smart_array_controller_is_hpe() -> None:
    out = build_storage_controller_resource(
        "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0",
        {"Id": "0", "Model": "HPE Smart Array E208i-a SR Gen10"},
    )
    assert out["Manufacturer"] == "HPE"


def test_supermicro_psu_model_names_the_maker() -> None:
    assert manufacturer_from_model("PWS-2K20A-1R") == "Supermicro"
    assert manufacturer_from_model("PWS-804P-1R") == "Supermicro"


def test_psu_without_manufacturer_uses_its_model() -> None:
    from normalizers.chassis.power_supplies.base import _power_supply_manufacturer

    ctx = NormalizationContext(
        data={"Manufacturer": None, "Model": "PWS-2K20A-1R"},
        client=None,
        logger=logging.getLogger("test"),
        vendor="Supermicro",
    )
    assert _power_supply_manufacturer(ctx) == "Supermicro"
