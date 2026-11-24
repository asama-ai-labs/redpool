# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""A slot name is not a drive Model, and remaining charge time is not a battery ChargeState."""

import logging
import unittest

from normalizers.chassis.drives.base import drive_model
from normalizers.systems.storage._hpe_smartstorage import build_battery_resource
from normalizers.types import NormalizationContext


def _drive_ctx(data):
    return NormalizationContext(
        data=data,
        client=None,
        logger=logging.getLogger("t"),
        vendor="Supermicro",
        resource_path="Chassis/1/Drives/Disk.Bay.0",
    )


class DriveModelTests(unittest.TestCase):
    def test_empty_bay_slot_name_is_not_copied_into_model(self) -> None:
        self.assertEqual(
            drive_model(_drive_ctx({"Name": "Disk.Bay.0", "Model": ""})), ""
        )

    def test_missing_model_is_empty_string(self) -> None:
        self.assertEqual(drive_model(_drive_ctx({"Name": "Disk.Bay.0"})), "")

    def test_reported_model_is_kept(self) -> None:
        self.assertEqual(
            drive_model(_drive_ctx({"Name": "Disk.Bay.1", "Model": " ST1000NM "})),
            "ST1000NM",
        )


class BatteryChargeStateTests(unittest.TestCase):
    def test_remaining_charge_time_does_not_imply_charging(self) -> None:
        body = build_battery_resource(
            "/redfish/v1/Chassis/1/Batteries/1",
            {"Index": 1, "RemainingChargeTimeSeconds": 37, "ChargeLevelPercent": 99},
        )
        self.assertIsNone(body["ChargeState"])


if __name__ == "__main__":
    unittest.main()
