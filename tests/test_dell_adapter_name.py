# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell adapters with no PCIe function take their name and model from DellNIC.ProductName."""

import logging

from normalizers.chassis.network_adapters.dell import (
    DellChassisNetworkAdapterNormalizer,
)
from normalizers.evaluator import evaluate
from normalizers.types import NormalizationContext

CH = "/redfish/v1/Chassis/System.Embedded.1"
ADAPTER = CH + "/NetworkAdapters/NIC.Embedded.1"
FN1 = ADAPTER + "/NetworkDeviceFunctions/NIC.Embedded.1-1-1"
FN2 = ADAPTER + "/NetworkDeviceFunctions/NIC.Embedded.2-1-1"


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


def _adapter(**extra):
    body = {
        "@odata.id": ADAPTER,
        "@odata.type": "#NetworkAdapter.v1_8_0.NetworkAdapter",
        "Id": "NIC.Embedded.1",
        "Name": "Network Adapter View",
        "Controllers": [
            {
                "Links": {
                    "NetworkDeviceFunctions": [{"@odata.id": FN1}, {"@odata.id": FN2}]
                }
            }
        ],
    }
    body.update(extra)
    return body


def _ndf(product):
    return {"Oem": {"Dell": {"DellNIC": {"ProductName": product}}}}


def _normalize(data, client):
    ctx = NormalizationContext(
        data=data,
        client=client,
        logger=logging.getLogger("t"),
        vendor="Dell",
        resource_path=ADAPTER,
    )
    normalizer = DellChassisNetworkAdapterNormalizer()
    normalizer.prefetch(ctx)
    return evaluate(normalizer.field_map(), ctx)


def test_name_and_model_come_from_the_nic_product_name():
    client = _Client({FN1: _ndf("Broadcom NetXtreme Gigabit Ethernet")})
    out = _normalize(_adapter(), client)
    assert out["Name"] == "Broadcom NetXtreme Gigabit Ethernet"
    assert out["Model"] == "Broadcom NetXtreme Gigabit Ethernet"


def test_the_manufacturer_is_not_inferred_from_the_product_name():
    client = _Client({FN1: _ndf("Broadcom NetXtreme Gigabit Ethernet")})
    out = _normalize(_adapter(), client)
    assert not out.get("Manufacturer")


def test_the_first_function_with_a_usable_name_is_used():
    client = _Client(
        {
            FN1: _ndf("00:1B:44:AA:BB:CC"),
            FN2: _ndf("Broadcom NetXtreme - 00:1B:44:AA:BB:CC"),
        }
    )
    assert _normalize(_adapter(), client)["Name"] == "Broadcom NetXtreme"


def test_a_real_bmc_name_and_model_are_kept():
    client = _Client({FN1: _ndf("Broadcom NetXtreme Gigabit Ethernet")})
    out = _normalize(_adapter(Name="My NIC", Model="Model X"), client)
    assert out["Name"] == "My NIC"
    assert out["Model"] == "Model X"


def test_without_a_product_name_the_adapter_is_unchanged():
    out = _normalize(_adapter(), _Client({}))
    assert out["Name"] == "Network Adapter View"
    assert not out.get("Model")


def test_a_failing_lookup_does_not_discard_the_adapter():
    class Raising(_Client):
        def get(self, path, args=None, headers=None):
            if "NetworkDeviceFunctions" in path:
                raise FileNotFoundError(path)
            return super().get(path, args, headers)

    out = _normalize(_adapter(), Raising({}))
    assert out["Name"] == "Network Adapter View"
    assert out["@odata.type"].startswith("#NetworkAdapter.")
