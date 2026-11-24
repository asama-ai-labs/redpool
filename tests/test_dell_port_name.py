# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell ``Port`` names: the generic iDRAC name is replaced by the PCIe function's model name."""

import logging

from normalizers.chassis.ports.dell import DellChassisPortNormalizer
from normalizers.evaluator import evaluate
from normalizers.types import NormalizationContext

CH = "/redfish/v1/Chassis/System.Embedded.1"
PORT = CH + "/NetworkAdapters/NIC.Slot.2/Ports/NIC.Slot.2-1"
DEV = CH + "/PCIeDevices/25-0"
FN = DEV + "/PCIeFunctions/25-0-0"
GENERIC = "Network Inteface Card(NIC) Port View"


class _Rest:
    def __init__(self, status, body):
        self.status = status
        self.dict = body
        self._http_response = None


class _Client:
    def __init__(self, bodies):
        self.bodies = bodies

    def get(self, path, args=None, headers=None):
        if path not in self.bodies:
            return _Rest(404, {})
        return _Rest(200, self.bodies[path])


def _bodies():
    return {
        CH + "/PCIeDevices": {"Members": [{"@odata.id": DEV}]},
        DEV: {
            "Name": "Mellanox adapter card",
            "PCIeFunctions": {"@odata.id": DEV + "/PCIeFunctions"},
        },
        DEV + "/PCIeFunctions": {"Members": [{"@odata.id": FN}]},
        FN: {
            "Name": "MT27710 Family [ConnectX-4 Lx]",
            "Links": {
                "EthernetInterfaces": [
                    {
                        "@odata.id": "/redfish/v1/Systems/System.Embedded.1"
                        "/EthernetInterfaces/NIC.Slot.2-1-1"
                    }
                ],
            },
        },
    }


def _port(name):
    return {
        "@odata.id": PORT,
        "@odata.type": "#Port.v1_8_0.Port",
        "Id": "NIC.Slot.2-1",
        "Name": name,
    }


def _normalize(name, client):
    ctx = NormalizationContext(
        data=_port(name),
        client=client,
        logger=logging.getLogger("t"),
        vendor="Dell",
        resource_path=PORT,
    )
    normalizer = DellChassisPortNormalizer()
    normalizer.prefetch(ctx)
    return evaluate(normalizer.field_map(), ctx)


def test_generic_dell_port_name_becomes_the_pcie_model_name():
    out = _normalize(GENERIC, _Client(_bodies()))
    assert out["Name"] == "MT27710 Family [ConnectX-4 Lx]"
    assert out["@odata.type"] == "#Port.v1_20_0.Port"


def test_a_real_bmc_name_is_kept():
    out = _normalize("My custom port", _Client(_bodies()))
    assert out["Name"] == "My custom port"


def test_name_stays_generic_when_no_pcie_function_matches():
    bodies = _bodies()
    bodies[FN]["Links"] = {"EthernetInterfaces": []}
    out = _normalize(GENERIC, _Client(bodies))
    assert out["Name"] == GENERIC


OEM = (
    CH
    + "/NetworkAdapters/NIC.Slot.2/NetworkDeviceFunctions/NIC.Slot.2-1"
    + "/Oem/Dell/DellNetworkAttributes/NIC.Slot.2-1"
)


def test_oem_device_name_wins_over_the_pcie_name_when_the_idrac_keys_it_by_port_id():
    bodies = _bodies()
    bodies[OEM] = {"Attributes": {"DeviceName": "HPE Eth 10/25Gb 2p 640SFP28 Adptr"}}
    out = _normalize(GENERIC, _Client(bodies))
    assert out["Name"] == "HPE Eth 10/25Gb 2p 640SFP28 Adptr"


class _RaisingClient(_Client):
    """A client whose lookup of a missing path raises instead of returning 404."""

    def get(self, path, args=None, headers=None):
        if path not in self.bodies:
            raise FileNotFoundError(path)
        return super().get(path, args, headers)


def test_a_failing_oem_lookup_does_not_discard_the_port():
    out = _normalize(GENERIC, _RaisingClient(_bodies()))
    assert out["Name"] == "MT27710 Family [ConnectX-4 Lx]"
    assert out["@odata.type"] == "#Port.v1_20_0.Port"


NDF = CH + "/NetworkAdapters/NIC.Slot.2/NetworkDeviceFunctions"


def _no_pcie(bodies):
    bodies[FN]["Links"] = {"EthernetInterfaces": []}
    return bodies


def _ndf(product):
    return {"Oem": {"Dell": {"DellNIC": {"ProductName": product}}}}


def test_nic_product_name_is_the_last_fallback():
    bodies = _no_pcie(_bodies())
    bodies[NDF + "/NIC.Slot.2-1-1"] = _ndf("Broadcom NetXtreme Gigabit Ethernet")
    assert _normalize(GENERIC, _Client(bodies))["Name"] == (
        "Broadcom NetXtreme Gigabit Ethernet"
    )


def test_nic_product_name_loses_its_mac_suffix():
    bodies = _no_pcie(_bodies())
    bodies[NDF + "/NIC.Slot.2-1-1"] = _ndf(
        "Intel(R) Ethernet 10G 4P X550/I350 rNDC - 00:1B:44:AA:BB:CC"
    )
    assert _normalize(GENERIC, _Client(bodies))["Name"] == (
        "Intel(R) Ethernet 10G 4P X550/I350 rNDC"
    )


def test_a_mac_address_is_not_a_name():
    bodies = _no_pcie(_bodies())
    bodies[NDF + "/NIC.Slot.2-1-1"] = _ndf("00:1B:44:AA:BB:CC")
    assert _normalize(GENERIC, _Client(bodies))["Name"] == GENERIC


def test_nic_product_name_is_found_when_the_function_id_is_the_port_id():
    bodies = _no_pcie(_bodies())
    bodies[NDF + "/NIC.Slot.2-1"] = _ndf("QLogic 577xx 10 Gb Ethernet")
    assert _normalize(GENERIC, _Client(bodies))["Name"] == "QLogic 577xx 10 Gb Ethernet"


def test_the_pcie_name_still_beats_the_nic_product_name():
    bodies = _bodies()
    bodies[NDF + "/NIC.Slot.2-1-1"] = _ndf("Some marketing name")
    assert (
        _normalize(GENERIC, _Client(bodies))["Name"] == "MT27710 Family [ConnectX-4 Lx]"
    )


PORT_ID = "NIC.Slot.3-1"
SLOT3 = CH + "/NetworkAdapters/NIC.Slot.3"
OEM3 = (
    SLOT3
    + "/NetworkDeviceFunctions/NIC.Slot.3-1/Oem/Dell/DellNetworkAttributes/NIC.Slot.3-1"
)
DEV3 = CH + "/PCIeDevices/94-0"
FN3 = DEV3 + "/PCIeFunctions/94-0-0"


def _slot3_bodies(link_attr="Connected", speed_attr="25Gbps"):
    return {
        OEM3: {"Attributes": {"LinkStatus": link_attr, "LnkSpeed": speed_attr}},
        CH + "/PCIeDevices": {"Members": [{"@odata.id": DEV3}]},
        DEV3: {
            "Name": "MT27710 Family [ConnectX-4 Lx]",
            "Status": {"Health": "OK", "State": "Enabled", "HealthRollup": "OK"},
            "PCIeFunctions": {"@odata.id": DEV3 + "/PCIeFunctions"},
        },
        DEV3 + "/PCIeFunctions": {"Members": [{"@odata.id": FN3}]},
        FN3: {
            "Name": "MT27710 Family [ConnectX-4 Lx]",
            "Links": {
                "EthernetInterfaces": [
                    {
                        "@odata.id": "/redfish/v1/Systems/System.Embedded.1"
                        "/EthernetInterfaces/NIC.Slot.3-1-1"
                    }
                ]
            },
        },
    }


def _slot3_port(**extra):
    path = SLOT3 + "/Ports/" + PORT_ID
    body = {
        "@odata.id": path,
        "@odata.type": "#Port.v1_8_0.Port",
        "Id": PORT_ID,
        "Name": GENERIC,
        "PortId": "3",
        "LinkStatus": "LinkDown",
        "CurrentSpeedGbps": 0,
        "Status": {"State": None, "Health": None, "HealthRollup": None},
    }
    body.update(extra)
    return body, path


def _normalize_slot3(body, path, client):
    ctx = NormalizationContext(
        data=body,
        client=client,
        logger=logging.getLogger("t"),
        vendor="Dell",
        resource_path=path,
    )
    normalizer = DellChassisPortNormalizer()
    normalizer.prefetch(ctx)
    return evaluate(normalizer.field_map(), ctx)


def test_an_unreadable_port_gets_its_real_link_speed_status_and_number():
    body, path = _slot3_port()
    out = _normalize_slot3(body, path, _Client(_slot3_bodies()))
    assert out["LinkStatus"] == "LinkUp"
    assert out["CurrentSpeedGbps"] == 25
    assert out["PortId"] == "1"
    assert out["Status"]["Health"] == "OK"
    assert out["Status"]["State"] == "Enabled"


def test_a_port_with_a_status_keeps_what_the_idrac_reports_over_the_oem_link_status():
    body, path = _slot3_port(
        LinkStatus="LinkUp",
        CurrentSpeedGbps=25,
        Status={"State": "Enabled", "Health": "OK", "HealthRollup": "OK"},
    )
    out = _normalize_slot3(body, path, _Client(_slot3_bodies(link_attr="Disconnected")))
    assert out["LinkStatus"] == "LinkUp"
    assert out["CurrentSpeedGbps"] == 25


def test_a_port_with_a_status_is_not_marked_up_by_the_oem_attributes():
    body, path = _slot3_port(
        Status={"State": "Enabled", "Health": "OK", "HealthRollup": "OK"}
    )
    out = _normalize_slot3(body, path, _Client(_slot3_bodies(link_attr="Connected")))
    assert out["LinkStatus"] == "LinkDown"


def test_an_unparseable_oem_speed_leaves_the_idrac_speed():
    body, path = _slot3_port()
    out = _normalize_slot3(body, path, _Client(_slot3_bodies(speed_attr="AutoNeg")))
    assert "CurrentSpeedGbps" not in out


def test_a_port_number_that_is_not_the_repeated_slot_is_kept():
    body, path = _slot3_port(PortId="2")
    out = _normalize_slot3(body, path, _Client(_slot3_bodies()))
    assert out["PortId"] == "2"
