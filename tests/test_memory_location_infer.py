# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""One inference and one passthrough per vendor for MemoryLocation.

Per-model DIMM tables live in the normalized fixtures.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import normalizers  # noqa: F401
from normalizers.optional import OMIT
from normalizers.registry import get_resource_entry
from normalizers.types import NormalizationContext


def _ctx(
    data: dict, vendor: str = "Dell Inc.", model: str = "PowerEdge R760"
) -> NormalizationContext:
    return NormalizationContext(
        data=data,
        client=None,
        logger=MagicMock(),
        vendor=vendor,
        model=model,
    )


def generate_memory_location(ctx: NormalizationContext):
    entry = get_resource_entry("Systems/Memory")
    value = entry.for_vendor(ctx.vendor).field_map()["MemoryLocation"](ctx)
    return None if value is OMIT else value


class TestMergeMemoryLocation(unittest.TestCase):
    def test_dell_infers_from_name(self):
        ctx = _ctx({"MemoryLocation": None, "Name": "DIMM A1"}, model="PowerEdge_R760")
        self.assertEqual(
            generate_memory_location(ctx),
            {"Socket": 0, "MemoryController": 0, "Channel": 0, "Slot": 0},
        )

    def test_dell_does_not_infer_without_name(self):
        ctx = _ctx(
            {
                "MemoryLocation": None,
                "DeviceLocator": "DIMM A1",
                "Id": "DIMM.Socket.A1",
            },
            model="PowerEdge_R760",
        )
        self.assertIsNone(generate_memory_location(ctx))

    def test_hpe_one_based_bmc_to_canonical(self):
        ctx = _ctx(
            {
                "MemoryLocation": {
                    "Socket": 2,
                    "MemoryController": 3,
                    "Channel": 2,
                    "Slot": 9,
                },
                "Name": "proc2dimm9",
            },
            vendor="HPE",
            model="ProLiant_DL360_Gen10",
        )
        self.assertEqual(
            generate_memory_location(ctx),
            {"Socket": 1, "MemoryController": 0, "Channel": 1, "Slot": 0},
        )

    def test_hpe_unknown_model_passes_complete_location_through(self):
        ml = {"Socket": 2, "MemoryController": 9, "Channel": 3, "Slot": 5}
        ctx = _ctx({"MemoryLocation": ml}, vendor="HPE", model="ProLiant_DL999_Fake")
        self.assertEqual(generate_memory_location(ctx), ml)

    def test_intel_slot_is_zero_based_within_channel(self):
        ctx = _ctx(
            {
                "MemoryLocation": {
                    "Socket": 0,
                    "MemoryController": 3,
                    "Channel": 6,
                    "Slot": 1,
                },
                "DeviceLocator": "CPU0_DIMM_G1",
            },
            vendor="Intel",
            model="M50CYP2SBSTD",
        )
        self.assertEqual(
            generate_memory_location(ctx),
            {"Socket": 0, "MemoryController": 3, "Channel": 6, "Slot": 0},
        )

    def test_intel_without_memory_location_returns_none(self):
        ctx = _ctx(
            {"MemoryLocation": None, "DeviceLocator": "CPU0_DIMM_A2"},
            vendor="Intel Corporation",
            model="M50CYP",
        )
        self.assertIsNone(generate_memory_location(ctx))

    def test_supermicro_passes_complete_location_through(self):
        ml = {"Socket": 1, "MemoryController": 1, "Channel": 7, "Slot": 0}
        ctx = _ctx(
            {"MemoryLocation": ml, "DeviceLocator": "P2-DIMMH1"},
            vendor="Supermicro",
            model="SYS-220TP-HTTR",
        )
        self.assertEqual(generate_memory_location(ctx), ml)

    def test_supermicro_unknown_silk_returns_none(self):
        ctx = _ctx(
            {"MemoryLocation": None, "DeviceLocator": "DIMMA99"},
            vendor="Supermicro",
            model="ARS-110M-NR",
        )
        self.assertIsNone(generate_memory_location(ctx))

    def test_lenovo_socket_and_slot_are_one_based(self):
        ctx = _ctx(
            {
                "MemoryLocation": {
                    "Socket": 1,
                    "MemoryController": 1,
                    "Channel": 2,
                    "Slot": 7,
                },
                "Name": "DIMM 7",
            },
            vendor="Lenovo",
            model="ThinkSystem_SR650_V2",
        )
        self.assertEqual(
            generate_memory_location(ctx),
            {"Socket": 0, "MemoryController": 1, "Channel": 2, "Slot": 0},
        )

    def test_lenovo_unknown_model_passes_complete_location_through(self):
        ml = {"Socket": 1, "MemoryController": 1, "Channel": 2, "Slot": 7}
        ctx = _ctx(
            {"MemoryLocation": ml}, vendor="Lenovo", model="ThinkSystem_Fake_999"
        )
        self.assertEqual(generate_memory_location(ctx), ml)

    def test_unknown_vendor_returns_none(self):
        ctx = _ctx({"MemoryLocation": None, "DeviceLocator": "weird"}, vendor="Contoso")
        self.assertIsNone(generate_memory_location(ctx))
