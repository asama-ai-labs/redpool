# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE SmartStorage resources take drive, volume and RAID fields from the native Storage."""

from __future__ import annotations

import unittest

import pytest

from normalizers.systems.storage._hpe_smartstorage import (
    build_storage_controller_resource,
    same_capacity,
)
from tests.test_hpe_smartstorage_storage import _proxy_request

DL360 = "ProLiant_DL360_Gen10"
NATIVE_DL360_RAID = ["RAID0", "RAID1", "RAID10", "RAID5", "None"]
FALLBACK_RAID_TYPES = ["RAID6", "RAID60", "RAID50", "RAID1Triple", "RAID10Triple"]


class TestSameCapacity(unittest.TestCase):
    def test_accepts_equal_and_within_one_mib(self) -> None:
        self.assertTrue(same_capacity(120034123776, 120034123776))
        self.assertTrue(same_capacity(120034123776, 120034123776 + 1024 * 1024))

    def test_rejects_larger_difference_and_missing_values(self) -> None:
        self.assertFalse(same_capacity(120034123776, 120034123776 + 2 * 1024 * 1024))
        self.assertFalse(same_capacity(None, 120034123776))
        self.assertFalse(same_capacity(120034123776, None))


class TestControllerRaidTypes(unittest.TestCase):
    def test_native_controller_with_same_model_supplies_raid_types(self) -> None:
        body = build_storage_controller_resource(
            "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0",
            {"Model": "P408i-a"},
            native={
                "Model": "P408i-a",
                "SupportedRAIDTypes": NATIVE_DL360_RAID,
                "SpeedGbps": 12.0,
            },
        )
        self.assertEqual(body["SupportedRAIDTypes"], NATIVE_DL360_RAID)
        self.assertEqual(body["SpeedGbps"], 12.0)

    def test_native_controller_with_other_model_is_ignored(self) -> None:
        body = build_storage_controller_resource(
            "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0",
            {"Model": "P408i-a"},
            native={"Model": "P816i-a", "SupportedRAIDTypes": NATIVE_DL360_RAID},
        )
        for raid in FALLBACK_RAID_TYPES:
            self.assertIn(raid, body["SupportedRAIDTypes"])
        self.assertNotIn("SpeedGbps", body)

    def test_without_native_controller_fallback_list_is_kept(self) -> None:
        body = build_storage_controller_resource(
            "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0",
            {"Model": "P408i-a"},
        )
        for raid in FALLBACK_RAID_TYPES:
            self.assertIn(raid, body["SupportedRAIDTypes"])
        self.assertNotIn("CacheSummary", body)


class TestProxyNativeFields(unittest.TestCase):
    @pytest.mark.requires_fixtures
    def test_smartstorage_drive_takes_native_speed_and_failure_prediction(self) -> None:
        body = _proxy_request(
            "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0/DiskDrives/6",
            model=DL360,
        )
        self.assertEqual(body["CapableSpeedGbs"], 6.0)
        self.assertEqual(body["FailurePredicted"], False)
        self.assertEqual(body["Identifiers"][0]["DurableNameFormat"], "NAA")

    @pytest.mark.requires_fixtures
    def test_controller_raid_types_come_from_native_controller(self) -> None:
        body = _proxy_request(
            "/redfish/v1/Systems/1/Storage/DE07A000/Controllers/0",
            model=DL360,
        )
        self.assertEqual(body["SupportedRAIDTypes"], NATIVE_DL360_RAID)
        self.assertEqual(body["SpeedGbps"], 12.0)
        self.assertEqual(body["CacheSummary"]["TotalCacheSizeMiB"], 128)

    @pytest.mark.requires_fixtures
    def test_volume_takes_native_cache_policies(self) -> None:
        body = _proxy_request(
            "/redfish/v1/Systems/1/SmartStorage/ArrayControllers/0/LogicalDrives/1",
            model=DL360,
        )
        self.assertEqual(body["ReadCachePolicy"], "Off")
        self.assertEqual(body["WriteCachePolicy"], "Off")
        self.assertEqual(body["IOPerfModeEnabled"], True)
        self.assertEqual(body["BlockSizeBytes"], 512)


if __name__ == "__main__":
    unittest.main()
