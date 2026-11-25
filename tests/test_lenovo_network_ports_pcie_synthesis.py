# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo: NetworkPorts filled from PCIe functions when BMC ``Ports`` collection is empty."""

from __future__ import annotations

import unittest
from pathlib import Path

import pytest

from redpool.proxy import RedfishProxy, ServerMetadata
from scripts.mockup_server import mockup_redfish_client

pytestmark = pytest.mark.requires_fixtures

_REPO = Path(__file__).resolve().parent.parent
_LENOVO_SR630_V2 = _REPO / "fixtures" / "Lenovo" / "ThinkSystem_SR630_V2"


def _proxy(metadata: ServerMetadata, path: str):
    proxy = RedfishProxy()
    with mockup_redfish_client(_LENOVO_SR630_V2) as client:
        return proxy.proxy_request(
            path,
            backend_client=client,
            server_metadata=metadata,
        )


class TestLenovoNetworkPortsPcieSynthesis(unittest.TestCase):
    def setUp(self) -> None:
        self.meta = ServerMetadata(
            hostname="mock.example.com",
            vendor="Lenovo",
            model="ThinkSystem SR630 V2",
        )

    def test_slot3_ports_collection_filled_from_pcie(self) -> None:
        path = "/redfish/v1/Chassis/1/NetworkAdapters/slot-3/Ports"
        body, _sm, status, norm_status, _ = _proxy(self.meta, path)
        self.assertEqual(status, 200)
        self.assertEqual(norm_status, "normalized")
        self.assertIsInstance(body, dict)
        members = body.get("Members")
        self.assertIsInstance(members, list)
        self.assertEqual(len(members), 2)
        ids = {m.get("@odata.id", "") for m in members if isinstance(m, dict)}
        self.assertIn(
            "/redfish/v1/Chassis/1/NetworkAdapters/slot-3/Ports/1",
            ids,
        )
        self.assertIn(
            "/redfish/v1/Chassis/1/NetworkAdapters/slot-3/Ports/2",
            ids,
        )
        self.assertEqual(body.get("Members@odata.count"), 2)

    def test_slot3_port_member_synthesized_when_missing_file(self) -> None:
        path = "/redfish/v1/Chassis/1/NetworkAdapters/slot-3/Ports/1"
        body, _sm, status, norm_status, _ = _proxy(self.meta, path)
        self.assertEqual(status, 200)
        self.assertEqual(norm_status, "normalized")
        self.assertIsInstance(body, dict)
        self.assertEqual(body.get("Id"), "1")
        self.assertEqual(body.get("@odata.type"), "#Port.v1_20_0.Port")
        self.assertIn("NetworkAdapter", body.get("Name", ""))
        oem = body.get("Oem")
        self.assertIsInstance(oem, dict)
        # Vendor-specific data lives in our own namespace; no invented LenovoPort type.
        rp = oem.get("Redpool") if isinstance(oem, dict) else None
        self.assertIsInstance(rp, dict)
        self.assertEqual(rp.get("PhysicalPortNumber"), "1")
        self.assertNotIn("LinkStatus", body)

    def test_slot1_ports_unchanged_when_bmc_has_members(self) -> None:
        path = "/redfish/v1/Chassis/1/NetworkAdapters/slot-1/Ports"
        body, _sm, status, _norm, _ = _proxy(self.meta, path)
        self.assertEqual(status, 200)
        self.assertIsInstance(body, dict)
        members = body.get("Members")
        self.assertIsInstance(members, list)
        self.assertEqual(len(members), 2)
        self.assertEqual(body.get("Members@odata.count"), 2)
