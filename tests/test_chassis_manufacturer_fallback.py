# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Chassis Manufacturer: the chassis, the linked ComputerSystem, or the vendor for a system chassis only."""

from __future__ import annotations

import logging

from normalizers.chassis.base import (
    BaseChassisNormalizer,
    _effective_chassis_manufacturer,
)
from normalizers.types import NormalizationContext
from normalizers.vendor_id import normalize_vendor_id


def _ctx(data: dict, **kwargs) -> NormalizationContext:
    return NormalizationContext(
        data=data,
        client=None,
        logger=logging.getLogger("test"),
        **kwargs,
    )


def test_chassis_manufacturer_unchanged_when_present() -> None:
    ctx = _ctx({"Manufacturer": "Dell Inc."})
    assert _effective_chassis_manufacturer(ctx) == "Dell Inc."


def test_chassis_manufacturer_from_prefetched_system() -> None:
    ctx = _ctx(
        {"Manufacturer": ""},
        prefetched={"server_manufacturer": "Dell Inc."},
    )
    assert _effective_chassis_manufacturer(ctx) == "Dell Inc."


def test_enclosure_manufacturer_is_not_the_server_vendor() -> None:
    # A storage enclosure or backplane is often made by someone else.
    ctx = _ctx({"Manufacturer": "", "ChassisType": "Enclosure"}, vendor="Dell")
    assert _effective_chassis_manufacturer(ctx) is None


def test_storage_enclosure_manufacturer_is_not_the_server_vendor() -> None:
    ctx = _ctx({"Manufacturer": "", "ChassisType": "StorageEnclosure"}, vendor="Dell")
    assert _effective_chassis_manufacturer(ctx) is None


def test_system_chassis_falls_back_to_server_vendor() -> None:
    ctx = _ctx({"Manufacturer": "", "ChassisType": "RackMount"}, vendor="Dell")
    assert _effective_chassis_manufacturer(ctx) == normalize_vendor_id("Dell")


def test_untyped_chassis_is_not_assumed_to_be_the_server_vendor() -> None:
    ctx = _ctx({"Manufacturer": ""}, vendor="Dell")
    assert _effective_chassis_manufacturer(ctx) is None


def test_linked_system_manufacturer_wins_over_vendor_fallback() -> None:
    ctx = _ctx(
        {"Manufacturer": "", "ChassisType": "RackMount"},
        vendor="Dell",
        prefetched={"server_manufacturer": "Supermicro"},
    )
    assert _effective_chassis_manufacturer(ctx) == normalize_vendor_id("Supermicro")


def test_field_map_uses_effective_manufacturer() -> None:
    mfr_fn = BaseChassisNormalizer().field_map()["Manufacturer"]
    ctx = _ctx(
        {"Manufacturer": ""},
        prefetched={"server_manufacturer": "HPE"},
    )
    assert mfr_fn(ctx) == "HPE"
