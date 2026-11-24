# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Tests for ``EccBits`` derivation from bus/data width in memory normalization."""

from __future__ import annotations

from normalizers.systems.memory.base import derive_ecc_bits_from_bus_data_widths


def test_ddr4_style_bus_minus_data():
    assert derive_ecc_bits_from_bus_data_widths(64, 72, "DDR4") == 8
    assert derive_ecc_bits_from_bus_data_widths(64, 72, "DDR4_SDRAM") == 8
    assert derive_ecc_bits_from_bus_data_widths(64, 72, None) == 8
    assert derive_ecc_bits_from_bus_data_widths(64, 72, "DDR3") == 8


def test_ddr5_halves_delta():
    assert derive_ecc_bits_from_bus_data_widths(64, 80, "DDR5") == 8
    assert derive_ecc_bits_from_bus_data_widths(64, 80, "DDR5_SDRAM") == 8


def test_no_ecc_when_bus_not_wider():
    assert derive_ecc_bits_from_bus_data_widths(64, 64, "DDR4") is None
    assert derive_ecc_bits_from_bus_data_widths(72, 64, "DDR4") is None


def test_missing_or_invalid_widths():
    assert derive_ecc_bits_from_bus_data_widths(None, 72, "DDR4") is None
    assert derive_ecc_bits_from_bus_data_widths(64, None, "DDR4") is None
