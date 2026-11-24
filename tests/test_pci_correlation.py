# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""PCI id parsing and HPE Chassis PCIeDevice to Systems PCIDevice correlation."""

import unittest

from normalizers.pci_class_code import pci_id_to_int
from normalizers.systems.pci_devices import hpe as pci_hpe

SYS = "/redfish/v1/Systems/1"
DEV = "/redfish/v1/Chassis/1/PCIeDevices/247"
IDS = {
    "VendorID": "0x10DE",
    "DeviceID": "0x2321",
    "SubsystemVendorID": "0x10DE",
    "SubsystemDeviceID": "0x1839",
}


class FakeRest:
    def __init__(self, status, body):
        self.status = status
        self.dict = body
        self._http_response = None


class FakeClient:
    def __init__(self, bodies):
        self.bodies = bodies

    def get(self, path, args=None, headers=None):
        if path not in self.bodies:
            return FakeRest(404, {})
        return FakeRest(200, self.bodies[path])


def _collection(*ids):
    return {"Members": [{"@odata.id": i} for i in ids]}


def _pcidev(n, slot):
    return {
        **IDS,
        "LocationString": f"PCI-E Slot {slot}",
        "BusNumber": 100 + n,
        "ClassCode": 3,
    }


def _bodies(*, devices=None):
    bodies = {
        DEV + "/PCIeFunctions": _collection(DEV + "/PCIeFunctions/1"),
        DEV + "/PCIeFunctions/1": {
            "VendorId": "4318",
            "DeviceId": "8993",
            "SubsystemVendorId": "4318",
            "SubsystemId": "6201",
        },
        SYS + "/PCIDevices": _collection(SYS + "/PCIDevices/6", SYS + "/PCIDevices/7"),
        SYS + "/PCIDevices/6": _pcidev(6, 9),
        SYS + "/PCIDevices/7": _pcidev(7, 16),
    }
    if devices:
        bodies["/redfish/v1/Chassis/1/Devices"] = _collection(*devices)
        bodies.update(devices)
    return bodies


class PciIdToIntTests(unittest.TestCase):
    def test_parser(self) -> None:
        self.assertEqual(pci_id_to_int("32902"), 0x8086)
        self.assertEqual(pci_id_to_int("0x10DE"), 0x10DE)
        self.assertEqual(pci_id_to_int("0X10de"), 0x10DE)
        self.assertEqual(pci_id_to_int("10de"), 0x10DE)
        self.assertEqual(pci_id_to_int(0x10DE), 0x10DE)
        self.assertIsNone(pci_id_to_int(True))
        self.assertIsNone(pci_id_to_int("zz"))
        self.assertIsNone(pci_id_to_int(None))
        self.assertEqual(pci_id_to_int(0x110DE), 0x10DE)


class MergeTests(unittest.TestCase):
    def _merge(self, bodies, chassis_body):
        return pci_hpe.merge_chassis_pcie_device_with_systems(
            FakeClient(bodies), DEV, chassis_body, SYS
        )

    def test_ambiguous_without_devices_assigns_no_slot(self) -> None:
        merged = self._merge(_bodies(), {"SerialNumber": "SN-A"})
        self.assertNotIn("LocationString", merged)
        self.assertNotIn("BusNumber", merged)
        self.assertEqual(merged["ClassCode"], 3)
        self.assertEqual(merged["VendorID"], "0x10DE")

    def test_dummy_serials_stay_ambiguous(self) -> None:
        devices = {
            "/redfish/v1/Chassis/1/Devices/6": {
                "SerialNumber": "DUMMY-SerialNumber",
                "DeviceInstances": [{"@odata.id": SYS + "/PCIDevices/6"}],
            },
            "/redfish/v1/Chassis/1/Devices/9": {
                "SerialNumber": "DUMMY-SerialNumber",
                "DeviceInstances": [{"@odata.id": SYS + "/PCIDevices/7"}],
            },
        }
        merged = self._merge(
            _bodies(devices=devices), {"SerialNumber": "DUMMY-SerialNumber"}
        )
        self.assertNotIn("LocationString", merged)

    def test_distinct_serials_pick_the_linked_candidate(self) -> None:
        devices = {
            "/redfish/v1/Chassis/1/Devices/6": {
                "SerialNumber": "SN-A",
                "DeviceInstances": [{"@odata.id": SYS + "/PCIDevices/6"}],
            },
            "/redfish/v1/Chassis/1/Devices/9": {
                "SerialNumber": "SN-B",
                "DeviceInstances": [{"@odata.id": SYS + "/PCIDevices/7"}],
            },
        }
        merged = self._merge(_bodies(devices=devices), {"SerialNumber": "SN-B"})
        self.assertEqual(merged["LocationString"], "PCI-E Slot 16")
        self.assertEqual(merged["BusNumber"], 107)

    def test_same_location_candidates_keep_first_match(self) -> None:
        bodies = _bodies()
        bodies[SYS + "/PCIDevices/7"] = {
            **_pcidev(7, 9),
            "StructuredName": "NIC.Slot.9.2",
        }
        bodies[SYS + "/PCIDevices/6"] = {
            **_pcidev(6, 9),
            "StructuredName": "NIC.Slot.9.1",
        }
        merged = self._merge(bodies, {})
        self.assertEqual(merged["LocationString"], "PCI-E Slot 9")
        self.assertEqual(merged["StructuredName"], "NIC.Slot.9.1")

    def test_single_candidate_merges(self) -> None:
        bodies = _bodies()
        bodies[SYS + "/PCIDevices"] = _collection(SYS + "/PCIDevices/6")
        merged = self._merge(bodies, {})
        self.assertEqual(merged["LocationString"], "PCI-E Slot 9")
        self.assertEqual(merged["BusNumber"], 106)


if __name__ == "__main__":
    unittest.main()
