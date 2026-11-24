# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell chassis PCIe inventory is walked once per context and shared by all matchers."""

import logging
import unittest
from collections import Counter

from normalizers.chassis.network_adapters.dell import (
    DellChassisNetworkAdapterNormalizer,
)
from normalizers.chassis.network_ports.dell import (
    prefetch_network_port_pcie_display,
    prefetch_network_port_pcie_status,
)
from normalizers.evaluator import evaluate
from normalizers.systems.ethernet_interfaces.dell import (
    prefetch_dell_ethernet_pcie_status,
)
from normalizers.types import NormalizationContext

CH = "/redfish/v1/Chassis/System.Embedded.1"
DEVS = CH + "/PCIeDevices"
D1 = DEVS + "/3-0"
D2 = DEVS + "/4-0"
D3 = DEVS + "/5-0"
D_GONE = DEVS + "/9-0"
ETH = "/redfish/v1/Systems/System.Embedded.1/EthernetInterfaces/NIC.Slot.3-1"


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

    @property
    def total(self):
        return sum(self.counts.values())


def _coll(*ids):
    return {"Members": [{"@odata.id": i} for i in ids]}


def _bodies():
    return {
        DEVS: _coll(D1, D_GONE, D2, D3),
        D1: {
            "Name": "Broadcom 57414",
            "Description": "Broadcom dual port NIC",
            "Manufacturer": "Broadcom",
            "FirmwareVersion": "21.80.9",
            "Slot": {"Location": {"PartLocation": {"LocationOrdinalValue": 3}}},
            "PCIeFunctions": {"@odata.id": D1 + "/PCIeFunctions"},
        },
        D1 + "/PCIeFunctions": _coll(
            D1 + "/PCIeFunctions/3-0-1", D1 + "/PCIeFunctions/3-0-2"
        ),
        D1 + "/PCIeFunctions/3-0-1": {
            "Name": "Port 1 function",
            "Description": "Port 1 desc",
            "DeviceClass": "NetworkController",
            "Status": {"Health": "OK", "State": "Enabled"},
            "Oem": {"Dell": {"DellPCIeFunction": {"Id": "NIC.Slot.3-1-1"}}},
            "Links": {"EthernetInterfaces": [{"@odata.id": ETH}]},
        },
        D1 + "/PCIeFunctions/3-0-2": {
            "Name": "Port 2 function",
            "DeviceClass": "NetworkController",
            "Oem": {"Dell": {"DellPCIeFunction": {"Id": "NIC.Slot.3-2-1"}}},
        },
        D2: {
            "Name": "GPU",
            "Description": "Accelerator",
            "Status": {"Health": "Critical", "State": "Enabled"},
            "PCIeFunctions": {"@odata.id": D2 + "/PCIeFunctions"},
        },
        D2 + "/PCIeFunctions": _coll(D2 + "/PCIeFunctions/4-0-1"),
        D2 + "/PCIeFunctions/4-0-1": {
            "DeviceClass": "DisplayController",
            "Status": {"Health": "Critical"},
        },
        D3: {
            "Name": "Mellanox ConnectX-6",
            "Description": "Mellanox NIC",
            "Manufacturer": "Mellanox",
            "FirmwareVersion": "22.31",
            "Slot": {"Location": {"PartLocation": {"LocationOrdinalValue": "5"}}},
            "PCIeFunctions": {"@odata.id": D3 + "/PCIeFunctions"},
        },
        D3 + "/PCIeFunctions": _coll(D3 + "/PCIeFunctions/5-0-1"),
        D3 + "/PCIeFunctions/5-0-1": {
            "DeviceClass": "NetworkController",
            "Status": {"Health": "Warning", "State": "Enabled"},
        },
    }


def _ctx(client, data, prefetched=None):
    return NormalizationContext(
        data=data,
        client=client,
        logger=logging.getLogger("test"),
        prefetched=prefetched if prefetched is not None else {},
        vendor="Dell",
    )


def _adapter(adapter_id):
    return {
        "@odata.id": f"{CH}/NetworkAdapters/{adapter_id}",
        "Id": adapter_id,
        "Name": "Network Adapter View",
        "Status": {"Health": "Unknown", "State": "Unknown"},
    }


def _port(port_id):
    return {
        "@odata.id": f"{CH}/NetworkAdapters/{port_id.rsplit('-', 1)[0]}/NetworkPorts/{port_id}",
        "Id": port_id,
        "Name": "Network Port View",
        "Status": {"Health": "Unknown"},
    }


def _normalize_adapter(client, adapter_id, prefetched=None):
    ctx = _ctx(client, _adapter(adapter_id), prefetched)
    n = DellChassisNetworkAdapterNormalizer()
    n.prefetch(ctx)
    return ctx, evaluate(n.field_map(), ctx)


class DellPcieWalkTests(unittest.TestCase):
    def test_adapter_walk_hits_each_path_at_most_once(self):
        client = CountingClient(_bodies())
        _normalize_adapter(client, "NIC.Slot.3")
        pcie_paths = {p: c for p, c in client.counts.items() if p.startswith(DEVS)}
        self.assertTrue(pcie_paths)
        self.assertTrue(all(c == 1 for c in pcie_paths.values()), pcie_paths)
        bound = 1 + (2 + 2) + (2 + 0) + (2 + 1) + (2 + 1) + 1
        self.assertLessEqual(sum(pcie_paths.values()), bound)

    def test_port_prefetch_reuses_adapter_walk(self):
        client = CountingClient(_bodies())
        shared = {}
        _normalize_adapter(client, "NIC.Slot.3", shared)
        before = Counter(client.counts)
        for fn in (
            prefetch_network_port_pcie_display,
            prefetch_network_port_pcie_status,
        ):
            ctx = _ctx(client, _port("NIC.Slot.3-1"), shared)
            fn(ctx)
        pcie_after = {p: c for p, c in client.counts.items() if p.startswith(DEVS)}
        pcie_before = {p: c for p, c in before.items() if p.startswith(DEVS)}
        self.assertEqual(pcie_after, pcie_before)

    def test_port_pair_walks_once(self):
        client = CountingClient(_bodies())
        shared = {}
        ctx = _ctx(client, _port("NIC.Slot.3-1"), shared)
        prefetch_network_port_pcie_display(ctx)
        prefetch_network_port_pcie_status(ctx)
        self.assertTrue(all(c == 1 for c in client.counts.values()), client.counts)

    def test_adapter_matched_by_function(self):
        client = CountingClient(_bodies())
        ctx, out = _normalize_adapter(client, "NIC.Slot.3")
        self.assertEqual(
            ctx.prefetched["_network_adapter_pcie_enrichment"],
            {
                "Model": "Broadcom 57414",
                "Manufacturer": "Broadcom",
                "Name": "Broadcom 57414",
                "FirmwareVersion": "21.80.9",
            },
        )
        self.assertEqual(
            ctx.prefetched["_dell_network_adapter_pcie_status"],
            {"Health": "OK", "State": "Enabled"},
        )
        self.assertEqual(out["Name"], "Broadcom 57414")
        self.assertEqual(out["Model"], "Broadcom 57414")
        self.assertEqual(out["Manufacturer"], "Broadcom")
        self.assertEqual(out["Controllers"], [{"FirmwarePackageVersion": "21.80.9"}])

    def test_adapter_status_from_first_function_when_device_has_none(self):
        client = CountingClient(_bodies())
        ctx, out = _normalize_adapter(client, "NIC.Slot.3")
        self.assertEqual(out["Status"]["Health"], "OK")
        self.assertEqual(out["Status"]["State"], "Enabled")

    def test_adapter_slot_fallback(self):
        client = CountingClient(_bodies())
        ctx, out = _normalize_adapter(client, "NIC.Slot.5")
        self.assertEqual(
            ctx.prefetched["_network_adapter_pcie_enrichment"],
            {
                "Model": "Mellanox ConnectX-6",
                "Manufacturer": "Mellanox",
                "Name": "Mellanox ConnectX-6",
                "FirmwareVersion": "22.31",
            },
        )
        self.assertNotIn("_dell_network_adapter_pcie_status", ctx.prefetched)

    def test_adapter_no_match(self):
        client = CountingClient(_bodies())
        ctx, out = _normalize_adapter(client, "NIC.Slot.7")
        self.assertNotIn("_network_adapter_pcie_enrichment", ctx.prefetched)
        self.assertNotIn("_dell_network_adapter_pcie_status", ctx.prefetched)

    def test_port_display_and_status(self):
        client = CountingClient(_bodies())
        ctx = _ctx(client, _port("NIC.Slot.3-1"))
        prefetch_network_port_pcie_display(ctx)
        prefetch_network_port_pcie_status(ctx)
        self.assertEqual(
            ctx.prefetched["_dell_network_port_pcie_display"],
            {"Name": "Port 1 function", "Description": "Port 1 desc"},
        )
        self.assertEqual(
            ctx.prefetched["_dell_network_port_pcie_status"],
            {"Health": "OK", "State": "Enabled"},
        )

    def test_port_display_falls_back_to_device(self):
        client = CountingClient(_bodies())
        ctx = _ctx(client, _port("NIC.Slot.3-2"))
        prefetch_network_port_pcie_display(ctx)
        prefetch_network_port_pcie_status(ctx)
        self.assertEqual(
            ctx.prefetched["_dell_network_port_pcie_display"],
            {"Name": "Port 2 function", "Description": "Broadcom dual port NIC"},
        )
        self.assertNotIn("_dell_network_port_pcie_status", ctx.prefetched)

    def test_ethernet_interface_status(self):
        client = CountingClient(_bodies())
        data = {
            "@odata.id": ETH,
            "Id": "NIC.Slot.3-1",
            "Status": {},
            "Links": {"Chassis": {"@odata.id": CH}},
        }
        ctx = _ctx(client, data)
        prefetch_dell_ethernet_pcie_status(ctx)
        self.assertEqual(
            ctx.prefetched["_dell_ethernet_pcie_status"],
            {"Health": "OK", "State": "Enabled"},
        )


if __name__ == "__main__":
    unittest.main()
