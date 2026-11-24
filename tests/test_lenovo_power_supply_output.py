# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Tests for Lenovo Chassis Power per-PSU output watts (power/lenovo.py)."""

from __future__ import annotations

from normalizers.chassis.power.lenovo import _normalize_power_supplies_lenovo
from normalizers.types import NormalizationContext


def test_lenovo_power_supplies_use_power_output_when_last_is_chassis_aggregate():
    ctx = NormalizationContext(
        data={
            "PowerSupplies": [
                {
                    "Name": "PSU1",
                    "MemberId": "0",
                    "LastPowerOutputWatts": 2285,
                    "PowerOutputWatts": 278,
                    "PowerInputWatts": 300,
                    "Manufacturer": "GREA",
                },
                {
                    "Name": "PSU2",
                    "MemberId": "1",
                    "LastPowerOutputWatts": 2285,
                    "PowerOutputWatts": 321,
                    "PowerInputWatts": 342,
                    "Manufacturer": "GREA",
                },
            ]
        },
        client=None,
        logger=None,
        vendor="Lenovo",
        model="ThinkSystem_SR680a_V3_310",
    )
    out = _normalize_power_supplies_lenovo(ctx)
    assert len(out) == 2
    assert out[0]["LastPowerOutputWatts"] == 278
    assert out[1]["LastPowerOutputWatts"] == 321


def test_lenovo_power_supplies_keep_last_when_plausible_per_psu():
    ctx = NormalizationContext(
        data={
            "PowerSupplies": [
                {
                    "Name": "PSU1",
                    "LastPowerOutputWatts": 150,
                    "PowerOutputWatts": 140,
                    "Manufacturer": "GREA",
                },
            ]
        },
        client=None,
        logger=None,
        vendor="Lenovo",
    )
    out = _normalize_power_supplies_lenovo(ctx)
    assert out[0]["LastPowerOutputWatts"] == 150
