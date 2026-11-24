# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""BaseSpeedMHz: vendor OEM clock values come from the vendor normalizer, not the base."""

from __future__ import annotations

import logging

from normalizers.systems.processors.base import resolve_base_speed
from normalizers.systems.processors.hpe import HPEProcessorNormalizer
from normalizers.systems.processors.lenovo import LenovoProcessorNormalizer
from normalizers.types import NormalizationContext


def _ctx(data: dict) -> NormalizationContext:
    return NormalizationContext(
        data=data,
        client=None,
        logger=logging.getLogger("test"),
        prefetched={},
        vendor="",
    )


def test_hpe_rated_speed_is_used_when_model_has_no_ghz() -> None:
    ctx = _ctx(
        {"Model": "Intel(R) Xeon(R) Gold 6430", "Oem": {"Hpe": {"RatedSpeedMHz": 2100}}}
    )
    assert HPEProcessorNormalizer().field_map()["BaseSpeedMHz"](ctx) == 2100


def test_lenovo_current_clock_is_used_when_model_has_no_ghz() -> None:
    ctx = _ctx(
        {
            "Model": "Intel(R) Xeon(R) Platinum 8568Y+",
            "Oem": {"Lenovo": {"CurrentClockSpeedMHz": 2300}},
        }
    )
    assert LenovoProcessorNormalizer().field_map()["BaseSpeedMHz"](ctx) == 2300


def test_base_ignores_vendor_oem_clock_without_a_vendor_path() -> None:
    assert resolve_base_speed(_ctx({"Oem": {"Hpe": {"RatedSpeedMHz": 2100}}})) is None
