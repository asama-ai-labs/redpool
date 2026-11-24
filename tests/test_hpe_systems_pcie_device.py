# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE Systems PCIeDevice keeps iLO location fields off the standard resource."""

from __future__ import annotations

from pathlib import Path

import pytest

from redpool.cache import InMemoryCache
from redpool.proxy import RedfishProxy, ServerMetadata
from redpool.schema_validator import validate_document
from tests.redpool import MockRedfishClient

pytestmark = pytest.mark.requires_fixtures

_DL360 = (
    Path(__file__).resolve().parent.parent / "fixtures" / "HPE" / "ProLiant_DL360_Gen10"
)


def test_rewritten_systems_pcie_device_is_schema_valid() -> None:
    client = MockRedfishClient(str(_DL360))
    proxy = RedfishProxy()
    proxy.objecttype_cache = InMemoryCache(ttl_seconds=60)
    path = "/redfish/v1/Systems/1/PCIeDevices/192"
    meta = ServerMetadata(
        hostname="dl360.example.com",
        vendor="HPE",
        model="ProLiant DL360 Gen10",
    )
    body, _meta, status, _norm, _headers = proxy.proxy_request(
        path,
        method="GET",
        redfish_endpoint="http://mock.example.com",
        backend_client=client,
        server_metadata=meta,
    )
    assert status == 200
    assert isinstance(body, dict)
    assert "Bifurcated" not in body
    assert "BusNumber" not in body
    assert "DeviceID" not in body
    assert "LocationString" not in body
    assert "VendorID" not in body
    assert body.get("DeviceType") != "Flexible LOM"
    assert body["Slot"]["Location"]["Info"] == "Embedded FlexibleLOM 1"
    assert "Redpool" not in body.get("Oem", {})
    assert "Hpe" not in body.get("Oem", {})
    result = validate_document(body)
    assert result.status == "valid", result.issues
