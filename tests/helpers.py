# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Unit tests for pure helper functions used by the proxy and normalizers."""

from __future__ import annotations

import http
import unittest
from unittest.mock import MagicMock

from normalizers.systems.processors.hpe import HPEProcessorNormalizer
from normalizers.systems.processors.lenovo import LenovoProcessorNormalizer
from normalizers.systems.processors.base import (
    _derive_part_number,
    processor_model,
    resolve_base_speed,
    _title_case_tier,
)
from normalizers.types import NormalizationContext
from normalizers.vendor_id import normalize_vendor_id
from redpool.config import _deep_merge
from redpool.proxy import BmcAuthError, _raise_if_unauthorized, _strip_redfish_v1_prefix


class TestStripRedfishV1Prefix(unittest.TestCase):
    """Tests for _strip_redfish_v1_prefix."""

    def test_strips_redfish_v1_prefix(self):
        self.assertEqual(
            _strip_redfish_v1_prefix(["redfish", "v1", "Systems", "1"]),
            ["Systems", "1"],
        )
        self.assertEqual(
            _strip_redfish_v1_prefix(["redfish", "v1"]),
            [],
        )

    def test_returns_unchanged_when_no_prefix(self):
        self.assertEqual(
            _strip_redfish_v1_prefix(["Systems", "1"]),
            ["Systems", "1"],
        )
        self.assertEqual(
            _strip_redfish_v1_prefix(["redfish"]),
            ["redfish"],
        )
        self.assertEqual(
            _strip_redfish_v1_prefix(["v1", "Chassis"]),
            ["v1", "Chassis"],
        )

    def test_empty_or_short_list(self):
        self.assertEqual(_strip_redfish_v1_prefix([]), [])
        self.assertEqual(_strip_redfish_v1_prefix(["redfish"]), ["redfish"])


class TestDeepMerge(unittest.TestCase):
    """Tests for config._deep_merge."""

    def test_shallow_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        self.assertEqual(_deep_merge(base, override), {"a": 1, "b": 3, "c": 4})
        self.assertEqual(base, {"a": 1, "b": 2})

    def test_deep_merge(self):
        base = {"cache": {"ttl": 60}, "proxy": {"port": 9101}}
        override = {"cache": {"ttl": 120}}
        self.assertEqual(
            _deep_merge(base, override),
            {"cache": {"ttl": 120}, "proxy": {"port": 9101}},
        )

    def test_override_replaces_non_dict_value(self):
        base = {"cache": {"ttl": 60}}
        override = {"cache": {"ttl": 90, "name": "default"}}
        self.assertEqual(
            _deep_merge(base, override), {"cache": {"ttl": 90, "name": "default"}}
        )


class TestRaiseIfUnauthorized(unittest.TestCase):
    """Tests for _raise_if_unauthorized."""

    def test_does_nothing_for_none_response(self):
        _raise_if_unauthorized(None, "/redfish/v1/Systems")

    def test_does_nothing_for_200(self):
        resp = MagicMock()
        resp.status = 200
        _raise_if_unauthorized(resp, "/redfish/v1/")

    def test_raises_for_401(self):
        resp = MagicMock()
        resp.status = http.HTTPStatus.UNAUTHORIZED.value
        with self.assertRaises(BmcAuthError) as ctx:
            _raise_if_unauthorized(resp, "/redfish/v1/Systems")
        self.assertIn("401", str(ctx.exception))
        self.assertIn("/redfish/v1/Systems", str(ctx.exception))

    def test_raises_for_403(self):
        resp = MagicMock()
        resp.status = http.HTTPStatus.FORBIDDEN.value
        with self.assertRaises(BmcAuthError) as ctx:
            _raise_if_unauthorized(resp, "/path")
        self.assertIn("403", str(ctx.exception))


class TestTitleCaseTier(unittest.TestCase):
    """Tests for _title_case_tier (Intel tier normalization)."""

    def test_capitalizes_platinum(self):
        self.assertEqual(_title_case_tier("PLATINUM 6248"), "Platinum 6248")

    def test_capitalizes_gold_silver_bronze(self):
        self.assertEqual(_title_case_tier("GOLD 5218"), "Gold 5218")
        self.assertEqual(_title_case_tier("SILVER 4216"), "Silver 4216")
        self.assertEqual(_title_case_tier("BRONZE 3204"), "Bronze 3204")

    def test_leaves_sku_unchanged(self):
        self.assertEqual(_title_case_tier("6248"), "6248")
        self.assertEqual(_title_case_tier("Xeon 6248"), "Xeon 6248")

    def test_single_word_tier(self):
        self.assertEqual(_title_case_tier("PLATINUM"), "Platinum")


def _make_ctx(data, config=None):
    return NormalizationContext(
        data=data,
        client=None,
        logger=MagicMock(),
        config=config,
    )


class TestDerivePartNumber(unittest.TestCase):
    """Tests for _derive_part_number."""

    def test_returns_part_number_when_present(self):
        ctx = _make_ctx({"PartNumber": "  ABC123  ", "Model": "Xeon(R) CPU"})
        self.assertEqual(_derive_part_number(ctx), "  ABC123  ")

    def test_returns_none_for_empty_part_number_and_no_model(self):
        ctx = _make_ctx({"PartNumber": "", "Model": ""})
        self.assertEqual(_derive_part_number(ctx), None)

    def test_derives_xeon_from_model(self):
        ctx = _make_ctx(
            {"PartNumber": "", "Model": "Xeon(R) CPU PLATINUM 6248 @ 2.50GHz"}
        )
        self.assertEqual(_derive_part_number(ctx), "Xeon Platinum 6248")

    def test_derives_epyc_from_model(self):
        ctx = _make_ctx({"PartNumber": "", "Model": "EPYC 7353"})
        self.assertEqual(_derive_part_number(ctx), "EPYC 7353")

    def test_derives_xeon_from_misplaced_processor_id_vendor_id(self):
        """Intel Rack Scale sometimes puts the full CPU marketing line in ProcessorId.VendorId."""
        ctx = _make_ctx(
            {
                "PartNumber": "",
                "Model": "Intel Xeon processor",
                "ProcessorId": {
                    "VendorId": "Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz",
                },
            }
        )
        self.assertEqual(_derive_part_number(ctx), "Xeon Gold 6338")

    def test_respects_config_derive_part_number_false(self):
        config = MagicMock()
        config.derive_part_number = False
        ctx = _make_ctx(
            {"PartNumber": "", "Model": "Xeon(R) CPU PLATINUM 6248"}, config=config
        )
        self.assertEqual(_derive_part_number(ctx), "")


class TestProcessorModel(unittest.TestCase):
    """Tests for processor_model (Intel Xeon display normalization)."""

    def test_enriches_generic_intel_xeon_model_from_vendor_id(self):
        ctx = _make_ctx(
            {
                "Model": "Intel Xeon processor",
                "ProcessorId": {
                    "VendorId": "Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz",
                },
            }
        )
        self.assertEqual(processor_model(ctx), "Intel(R) Xeon(R) Gold 6338")

    def test_scalable_xeon_strips_cpu_at_ghz(self):
        ctx = _make_ctx(
            {
                "Model": "Intel(R) Xeon(R) Gold 6230R CPU @ 2.10GHz",
                "ProcessorId": {"VendorId": "Intel(R) Corporation"},
            }
        )
        self.assertEqual(processor_model(ctx), "Intel(R) Xeon(R) Gold 6230R")

    def test_legacy_xeon_e5_strips_at_ghz_and_cpu_token(self):
        ctx = _make_ctx(
            {
                "Model": "Intel(R) Xeon(R) CPU E5-2650 v4 @ 2.20GHz",
                "ProcessorId": {"VendorId": "Intel(R) Corporation"},
            }
        )
        self.assertEqual(processor_model(ctx), "Intel(R) Xeon(R) E5-2650 v4")

    def test_normalizes_uppercase_intel_xeon_tier(self):
        ctx = _make_ctx(
            {
                "Model": "INTEL(R) XEON(R) PLATINUM 8568Y+",
                "Oem": {"Lenovo": {"CurrentClockSpeedMHz": 2300}},
            }
        )
        self.assertEqual(processor_model(ctx), "Intel(R) Xeon(R) Platinum 8568Y+")

    def test_passes_through_intel_model_without_speed_suffix(self):
        ctx = _make_ctx({"Model": "Intel(R) Xeon(R) Gold 6430"})
        self.assertEqual(processor_model(ctx), "Intel(R) Xeon(R) Gold 6430")

    def test_amd_epyc_passes_through_full_model_string(self):
        ctx = _make_ctx({"Model": "AMD EPYC 7763 64-Core Processor                "})
        self.assertEqual(processor_model(ctx), "AMD EPYC 7763 64-Core Processor")

    def test_amd_epyc_passes_through_32_core_form(self):
        ctx = _make_ctx({"Model": "AMD EPYC 9334 32-Core Processor"})
        self.assertEqual(processor_model(ctx), "AMD EPYC 9334 32-Core Processor")

    def test_returns_none_when_model_absent(self):
        self.assertEqual(processor_model(_make_ctx({})), None)

    def test_returns_non_string_model_as_is(self):
        ctx = _make_ctx({"Model": 12345})
        self.assertEqual(processor_model(ctx), 12345)


class TestResolveBaseSpeed(unittest.TestCase):
    """Tests for resolve_base_speed."""

    def test_returns_basespeed_mhz_when_present(self):
        ctx = _make_ctx({"BaseSpeedMHz": 2500})
        self.assertEqual(resolve_base_speed(ctx), 2500)

    def test_fallback_to_operating_speed_mhz(self):
        ctx = _make_ctx({"OperatingSpeedMHz": 2400})
        self.assertEqual(resolve_base_speed(ctx), 2400)

    def test_fallback_to_hpe_rated_speed_mhz_when_model_has_no_ghz(self):
        ctx = _make_ctx(
            {
                "Model": "Intel(R) Xeon(R) Gold 6430",
                "Oem": {"Hpe": {"RatedSpeedMHz": 2100}},
            }
        )
        self.assertEqual(
            HPEProcessorNormalizer().field_map()["BaseSpeedMHz"](ctx), 2100
        )

    def test_fallback_to_lenovo_current_clock_mhz_when_model_has_no_ghz(self):
        ctx = _make_ctx(
            {
                "Model": "Intel(R) Xeon(R) Platinum 8568Y+",
                "Oem": {"Lenovo": {"CurrentClockSpeedMHz": 2300}},
            }
        )
        self.assertEqual(
            LenovoProcessorNormalizer().field_map()["BaseSpeedMHz"](ctx), 2300
        )

    def test_base_ignores_vendor_oem_clock_without_a_vendor_path(self):
        ctx = _make_ctx({"Oem": {"Hpe": {"RatedSpeedMHz": 2100}}})
        self.assertIsNone(resolve_base_speed(ctx))

    def test_parses_from_model_ghz(self):
        ctx = _make_ctx({"Model": "Xeon(R) CPU PLATINUM 6248 @ 2.50GHz"})
        self.assertEqual(resolve_base_speed(ctx), 2500)

    def test_ignores_zero_basespeed_parses_model(self):
        """BMC may send BaseSpeedMHz: 0 while nominal GHz is only in Model."""
        ctx = _make_ctx(
            {
                "BaseSpeedMHz": 0,
                "Model": "Intel(R) Xeon(R) Gold 6430 CPU @ 2.10GHz",
                "MaxSpeedMHz": 4000,
            }
        )
        self.assertEqual(resolve_base_speed(ctx), 2100)

    def test_parses_ghz_from_misplaced_processor_id_vendor_id(self):
        ctx = _make_ctx(
            {
                "Model": "Intel Xeon processor",
                "ProcessorId": {
                    "VendorId": "Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz",
                },
            }
        )
        self.assertEqual(resolve_base_speed(ctx), 2000)

    def test_returns_none_when_no_data(self):
        ctx = _make_ctx({})
        self.assertEqual(resolve_base_speed(ctx), None)

    def test_respects_config_derive_base_speed_false(self):
        config = MagicMock()
        config.derive_base_speed = False
        ctx = _make_ctx({"Model": "Xeon @ 2.50GHz"})
        ctx.config = config
        self.assertEqual(resolve_base_speed(ctx), None)

    def test_literal_zero_when_derive_disabled(self):
        config = MagicMock()
        config.derive_base_speed = False
        ctx = _make_ctx({"BaseSpeedMHz": 0, "Model": "Xeon @ 9.99GHz"}, config=config)
        self.assertEqual(resolve_base_speed(ctx), 0)


class TestNormalizeVendorId(unittest.TestCase):
    """Tests for normalize_vendor_id (AMD / Intel canonical names)."""

    def test_amd_short_form(self):
        self.assertEqual(normalize_vendor_id("AMD"), "Advanced Micro Devices, Inc.")
        self.assertEqual(normalize_vendor_id("  amd  "), "Advanced Micro Devices, Inc.")

    def test_amd_long_form_unchanged_canonical(self):
        self.assertEqual(
            normalize_vendor_id("Advanced Micro Devices, Inc."),
            "Advanced Micro Devices, Inc.",
        )


if __name__ == "__main__":
    unittest.main()
