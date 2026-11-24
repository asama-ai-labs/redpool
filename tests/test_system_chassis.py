# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""The HPE chassis comes from the system, not a literal ``Chassis/1``."""

import unittest

from normalizers._shared import system_chassis
from normalizers._shared.system_chassis import (
    begin_system_chassis_memo,
    chassis_for_system,
    chassis_from_system_body,
)
from normalizers.pcie_display import _parent_pcie_device_candidates
from normalizers.systems.pci_devices import hpe as pci_hpe
from normalizers.systems.storage import hpe as storage_hpe


class FakeRest:
    def __init__(self, status, body):
        self.status = status
        self.dict = body
        self._http_response = None


class FakeClient:
    def __init__(self, bodies):
        self.bodies = bodies
        self.calls = []

    def get(self, path, args=None, headers=None):
        self.calls.append(path)
        if path not in self.bodies:
            return FakeRest(404, {})
        return FakeRest(200, self.bodies[path])


def _system(chassis):
    return {"Links": {"Chassis": [{"@odata.id": c} for c in chassis]}}


def _collection(*ids):
    return {"Members": [{"@odata.id": i} for i in ids]}


BLADE = "/redfish/v1/Chassis/Blade2"


class SystemChassisTests(unittest.TestCase):
    def tearDown(self) -> None:
        system_chassis._memo.set(None)

    def test_from_body(self) -> None:
        self.assertEqual(chassis_from_system_body(_system([BLADE + "/"])), BLADE)
        self.assertIsNone(chassis_from_system_body({}))

    def test_links_win_over_collection(self) -> None:
        client = FakeClient(
            {
                "/redfish/v1/Systems/1": _system([BLADE]),
                "/redfish/v1/Chassis": _collection("/redfish/v1/Chassis/1"),
            }
        )
        self.assertEqual(chassis_for_system(client, "1"), BLADE)

    def test_single_member_collection_fallback(self) -> None:
        client = FakeClient(
            {
                "/redfish/v1/Systems/1": {},
                "/redfish/v1/Chassis": _collection(BLADE),
            }
        )
        self.assertEqual(chassis_for_system(client, "1"), BLADE)

    def test_ambiguous_is_none(self) -> None:
        client = FakeClient(
            {
                "/redfish/v1/Systems/1": {},
                "/redfish/v1/Chassis": _collection(BLADE, "/redfish/v1/Chassis/1"),
            }
        )
        self.assertIsNone(chassis_for_system(client, "1"))

    def test_memo_avoids_second_get(self) -> None:
        client = FakeClient({"/redfish/v1/Systems/1": _system([BLADE])})
        begin_system_chassis_memo()
        self.assertEqual(chassis_for_system(client, "1"), BLADE)
        self.assertEqual(chassis_for_system(client, "1"), BLADE)
        self.assertEqual(client.calls, ["/redfish/v1/Systems/1"])

    def test_no_memo_by_default(self) -> None:
        client = FakeClient({"/redfish/v1/Systems/1": _system([BLADE])})
        chassis_for_system(client, "1")
        chassis_for_system(client, "1")
        self.assertEqual(len(client.calls), 2)

    def test_pcie_backend_uses_blade_chassis(self) -> None:
        client = FakeClient(
            {
                "/redfish/v1/Systems/1": _system([BLADE]),
                BLADE + "/PCIeDevices": _collection(BLADE + "/PCIeDevices/3"),
            }
        )
        backend, from_prefix, to_prefix = pci_hpe._hpe_resolve_backend(
            client, "/redfish/v1/Systems/1/PCIeDevices/3"
        )
        self.assertEqual(backend, BLADE + "/PCIeDevices/3")
        self.assertEqual(from_prefix, BLADE + "/PCIeDevices")
        self.assertEqual(to_prefix, "/redfish/v1/Systems/1/PCIeDevices")

    def test_pcie_backend_without_client_falls_back_to_chassis_1(self) -> None:
        self.assertEqual(
            pci_hpe._hpe_systems_pcie_backend_path("/redfish/v1/Systems/1/PCIeDevices"),
            "/redfish/v1/Chassis/1/PCIeDevices",
        )

    def test_battery_backend_uses_blade_chassis(self) -> None:
        path = "/redfish/v1/Systems/1/Storage/DE00/Controllers/0/Batteries"
        self.assertEqual(
            storage_hpe._hpe_storage_backend_path(path, BLADE),
            BLADE,
        )
        self.assertEqual(
            storage_hpe._hpe_storage_response_rewrite(path, BLADE)[0],
            BLADE,
        )

    def test_parent_pcie_device_candidate_uses_blade_chassis(self) -> None:
        client = FakeClient({"/redfish/v1/Systems/1": _system([BLADE])})
        oid = "/redfish/v1/Systems/1/PCIeDevices/3/PCIeFunctions/1"
        self.assertEqual(
            _parent_pcie_device_candidates(oid, client)[1],
            BLADE + "/PCIeDevices/3",
        )


if __name__ == "__main__":
    unittest.main()
