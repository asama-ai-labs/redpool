# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Fields the capture has and the output used to drop: memory media, thermal status,
HPE memory health, Supermicro drive form factor and Dell NIC vendor."""

from __future__ import annotations

import logging
import unittest
from collections import Counter

from normalizers.chassis.drives.supermicro import SupermicroChassisDriveNormalizer
from normalizers.chassis.network_adapters.dell import effective_adapter_manufacturer
from normalizers.chassis.thermal.base import BaseThermalNormalizer
from normalizers.evaluator import evaluate
from normalizers.systems.computer_system.hpe import _hpe_memory_summary
from normalizers.systems.memory.dell_memory import _dell_memory_media
from normalizers._shared.dell_nic_product import nic_fields
from normalizers.types import NormalizationContext


class FakeRest:
    def __init__(self, status, body):
        self.status = status
        self.dict = body
        self._http_response = None


class CountingClient:
    def __init__(self, bodies):
        self.bodies = bodies
        self.counts = Counter()

    def get(self, path, args=None, headers=None):
        self.counts[path] += 1
        if path not in self.bodies:
            return FakeRest(404, {})
        return FakeRest(200, self.bodies[path])


def _ctx(data, client=None, odata_id="", prefetched=None):
    if odata_id:
        data = {**data, "@odata.id": odata_id}
    return NormalizationContext(
        data=data,
        client=client,
        logger=logging.getLogger("test"),
        prefetched=prefetched if prefetched is not None else {},
        vendor="Dell",
    )


class DellMemoryMediaTests(unittest.TestCase):
    def test_dram_technology_becomes_memory_media(self) -> None:
        data = {"Oem": {"Dell": {"DellMemory": {"MemoryTechnology": "DRAM"}}}}
        self.assertEqual(_dell_memory_media(_ctx(data)), ["DRAM"])

    def test_bmc_memory_media_is_kept(self) -> None:
        data = {
            "MemoryMedia": ["NAND"],
            "Oem": {"Dell": {"DellMemory": {"MemoryTechnology": "DRAM"}}},
        }
        self.assertEqual(_dell_memory_media(_ctx(data)), ["NAND"])

    def test_other_or_missing_technology_is_left_out(self) -> None:
        other = {"Oem": {"Dell": {"DellMemory": {"MemoryTechnology": "Flash"}}}}
        self.assertEqual(_dell_memory_media(_ctx(other)), [])
        self.assertEqual(_dell_memory_media(_ctx({})), [])


class ThermalSubsystemStatusTests(unittest.TestCase):
    THERMAL = "/redfish/v1/Chassis/System.Embedded.1/Thermal"
    SUBSYSTEM = "/redfish/v1/Chassis/System.Embedded.1/ThermalSubsystem"

    def _prefetch_and_map(self, data, bodies):
        client = CountingClient(bodies)
        ctx = _ctx(data, client=client, odata_id=self.THERMAL)
        normalizer = BaseThermalNormalizer()
        normalizer.prefetch(ctx)
        return client, evaluate(normalizer.field_map(), ctx)

    def test_missing_thermal_status_takes_subsystem_status(self) -> None:
        client, out = self._prefetch_and_map(
            {"Id": "Thermal", "Temperatures": []},
            {self.SUBSYSTEM: {"Status": {"State": "Enabled", "Health": "OK"}}},
        )
        self.assertEqual(client.counts[self.SUBSYSTEM], 1)
        self.assertEqual(out["Status"], {"State": "Enabled", "Health": "OK"})

    def test_own_thermal_status_is_kept_without_a_read(self) -> None:
        client, out = self._prefetch_and_map(
            {"Id": "Thermal", "Status": {"State": "Enabled", "Health": "Warning"}},
            {self.SUBSYSTEM: {"Status": {"State": "Enabled", "Health": "OK"}}},
        )
        self.assertNotIn(self.SUBSYSTEM, client.counts)
        self.assertEqual(out["Status"], {"State": "Enabled", "Health": "Warning"})

    def test_unreadable_subsystem_leaves_status_empty(self) -> None:
        _client, out = self._prefetch_and_map({"Id": "Thermal"}, {})
        self.assertEqual(out["Status"], {"State": None, "Health": None})


class HpeMemorySummaryTests(unittest.TestCase):
    def test_health_comes_from_aggregate_memory_health(self) -> None:
        data = {
            "MemorySummary": {
                "TotalSystemMemoryGiB": 128,
                "Status": {"HealthRollup": "OK"},
            },
            "Oem": {
                "Hpe": {
                    "AggregateHealthStatus": {"Memory": {"Status": {"Health": "OK"}}}
                }
            },
        }
        out = _hpe_memory_summary(_ctx(data))
        self.assertEqual(out["Status"]["Health"], "OK")
        self.assertEqual(out["Status"]["HealthRollup"], "OK")
        self.assertEqual(out["TotalSystemMemoryGiB"], 128)

    def test_health_falls_back_to_rollup(self) -> None:
        data = {"MemorySummary": {"Status": {"HealthRollup": "Warning"}}}
        self.assertEqual(_hpe_memory_summary(_ctx(data))["Status"]["Health"], "Warning")

    def test_no_status_is_not_invented(self) -> None:
        out = _hpe_memory_summary(_ctx({"MemorySummary": {"TotalSystemMemoryGiB": 8}}))
        self.assertNotIn("Status", out)


class SupermicroDriveFormFactorTests(unittest.TestCase):
    def test_drive_form_factor_is_passed_through(self) -> None:
        data = {"Name": "Disk.Bay.0", "Protocol": "NVMe", "DriveFormFactor": "U2"}
        out = evaluate(SupermicroChassisDriveNormalizer().field_map(), _ctx(data))
        self.assertEqual(out["DriveFormFactor"], "U2")

    def test_absent_form_factor_is_omitted(self) -> None:
        out = evaluate(
            SupermicroChassisDriveNormalizer().field_map(),
            _ctx({"Name": "Disk.Bay.0"}),
        )
        self.assertNotIn("DriveFormFactor", out)


class DellNicVendorTests(unittest.TestCase):
    F1 = "/redfish/v1/Systems/System.Embedded.1/NetworkDeviceFunctions/NIC.Embedded.1-1-1"
    F2 = "/redfish/v1/Systems/System.Embedded.1/NetworkDeviceFunctions/NIC.Embedded.1-2-1"

    def _bodies(self):
        return {
            self.F1: {
                "Oem": {"Dell": {"DellNIC": {"ProductName": "00:11:22:33:44:55"}}}
            },
            self.F2: {
                "Oem": {
                    "Dell": {
                        "DellNIC": {
                            "ProductName": "BCM5720 - 00:11:22:33:44:55",
                            "VendorName": "Broadcom Corp",
                        }
                    }
                }
            },
        }

    def test_vendor_name_is_read_from_the_first_function_that_has_it(self) -> None:
        client = CountingClient(self._bodies())
        found = nic_fields(client, [self.F1, self.F2], ("VendorName",))
        self.assertEqual(found, {"VendorName": "Broadcom Corp"})
        self.assertEqual(client.counts[self.F2], 1)

    def test_walk_stops_once_every_wanted_field_is_found(self) -> None:
        client = CountingClient(self._bodies())
        found = nic_fields(client, [self.F2, self.F1], ("ProductName", "VendorName"))
        self.assertEqual(found["ProductName"], "BCM5720")
        self.assertEqual(found["VendorName"], "Broadcom Corp")
        self.assertNotIn(self.F1, client.counts)

    def test_adapter_manufacturer_uses_nic_vendor_when_nothing_else_has_one(
        self,
    ) -> None:
        ctx = _ctx(
            {"Id": "NIC.Embedded.1"},
            prefetched={"_dell_network_adapter_nic_vendor": "Broadcom Corp"},
        )
        self.assertEqual(effective_adapter_manufacturer(ctx), "Broadcom Corp")

    def test_adapter_manufacturer_prefers_the_bmc_value(self) -> None:
        ctx = _ctx(
            {"Id": "NIC.Slot.3", "Manufacturer": "Broadcom"},
            prefetched={"_dell_network_adapter_nic_vendor": "Broadcom Corp"},
        )
        self.assertEqual(effective_adapter_manufacturer(ctx), "Broadcom")


if __name__ == "__main__":
    unittest.main()
