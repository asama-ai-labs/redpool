# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Tests for HPE SmartStorage-only storage normalization."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pytest

from redpool.proxy import RedfishProxy, ServerMetadata
from redpool.schema_validator import validate_document
from scripts.mockup_server import mockup_redfish_client


def _proxy_request(
    path: str,
    model: str = "ProLiant_DL380_Gen10_2",
    *,
    fixtures: Path = Path(__file__).resolve().parent.parent / "fixtures",
) -> dict:
    model_dir = fixtures / "HPE" / model
    if not (model_dir / "original").is_dir():
        pytest.skip(f"HPE {model} fixture is unavailable")
    proxy = RedfishProxy()
    metadata = ServerMetadata(
        hostname="mock.example.com",
        vendor="HPE",
        model="ProLiant DL380 Gen10",
    )
    with mockup_redfish_client(model_dir) as client:
        body, _, status, norm_status, _ = proxy.proxy_request(
            path,
            backend_client=client,
            server_metadata=metadata,
        )
    assert status == 200
    assert norm_status == "normalized"
    assert isinstance(body, dict)
    return body


class TestHPESmartStorageNormalization(unittest.TestCase):
    @pytest.mark.requires_fixtures
    def test_hpe_smartstorage_synthesizes_storage_collection(self) -> None:
        body = _proxy_request("/redfish/v1/Systems/1/Storage")
        self.assertEqual(body["@odata.type"], "#StorageCollection.StorageCollection")
        self.assertEqual(
            body["Members"], [{"@odata.id": "/redfish/v1/Systems/1/Storage/0"}]
        )
        self.assertEqual(body["Members@odata.count"], 1)

    @pytest.mark.requires_fixtures
    def test_hpe_smartstorage_synthesizes_storage_member(self) -> None:
        body = _proxy_request("/redfish/v1/Systems/1/Storage/0")
        self.assertEqual(body["@odata.type"], "#Storage.v1_16_0.Storage")
        self.assertEqual(body["Id"], "0")
        self.assertEqual(body["Drives@odata.count"], 2)
        self.assertEqual(
            body["Volumes"]["@odata.id"],
            "/redfish/v1/Systems/1/Storage/0/Volumes",
        )
        self.assertEqual(
            body["Controllers"]["@odata.id"],
            "/redfish/v1/Systems/1/Storage/0/Controllers",
        )

    @pytest.mark.requires_fixtures
    def test_hpe_smartstorage_drive_and_volume_membership(self) -> None:
        drive = _proxy_request("/redfish/v1/Systems/1/Storage/0/Drives/2")
        self.assertEqual(drive["@odata.type"], "#Drive.v1_19_0.Drive")
        self.assertEqual(drive["Id"], "2")
        self.assertEqual(drive["Protocol"], "SATA")
        self.assertEqual(drive["CapacityBytes"], 120034123776)

        volumes = _proxy_request("/redfish/v1/Systems/1/Storage/0/Volumes")
        self.assertEqual(
            volumes["Members"],
            [{"@odata.id": "/redfish/v1/Systems/1/Storage/0/Volumes/1"}],
        )

        volume = _proxy_request("/redfish/v1/Systems/1/Storage/0/Volumes/1")
        self.assertEqual(volume["@odata.type"], "#Volume.v1_10_0.Volume")
        self.assertEqual(volume["RAIDType"], "RAID1")
        self.assertEqual(
            volume["Links"]["Drives"],
            [
                {"@odata.id": "/redfish/v1/Systems/1/Storage/0/Drives/2"},
                {"@odata.id": "/redfish/v1/Systems/1/Storage/0/Drives/3"},
            ],
        )

    @pytest.mark.requires_fixtures
    def test_hpe_smartstorage_controller_links_battery(self) -> None:
        controller = _proxy_request("/redfish/v1/Systems/1/Storage/0/Controllers/0")
        self.assertEqual(
            controller["@odata.type"],
            "#StorageController.v1_7_0.StorageController",
        )
        self.assertEqual(
            controller["Links"]["Batteries"],
            [
                {
                    "@odata.id": "/redfish/v1/Systems/1/Storage/0/Controllers/0/Batteries/1"
                }
            ],
        )

        battery = _proxy_request(
            "/redfish/v1/Systems/1/Storage/0/Controllers/0/Batteries/1"
        )
        self.assertEqual(battery["@odata.type"], "#Battery.v1_5_0.Battery")
        self.assertEqual(battery["Model"], "875241-B21")
        self.assertEqual(battery["SparePartNumber"], "878643-001")
        self.assertEqual(battery["Status"]["Health"], "OK")

    def test_hpe_array_controller_serial_number_trimmed(self) -> None:
        import logging

        from normalizers.systems.smart_storage.array_controllers.base import (
            BaseSmartStorageArrayControllerNormalizer,
        )
        from normalizers.systems.storage._hpe_smartstorage import (
            build_storage_controller_resource,
        )
        from normalizers.types import NormalizationContext

        raw = {
            "Id": "0",
            "Model": "HPE Smart Array P408i-a SR Gen10",
            "SerialNumber": "SN-TEST-0001 ",
        }
        built = build_storage_controller_resource(
            "/redfish/v1/Systems/1/Storage/0/Controllers/0",
            raw,
        )
        self.assertEqual(built["SerialNumber"], "SN-TEST-0001")

        ctx = NormalizationContext(
            data=raw,
            client=None,
            logger=logging.getLogger("test"),
            vendor="HPE",
            model="ProLiant",
        )
        sn = BaseSmartStorageArrayControllerNormalizer().field_map()["SerialNumber"]
        self.assertEqual(sn(ctx), "SN-TEST-0001")

    def test_smartstorage_drive_keeps_vendor_oem(self) -> None:
        from normalizers.systems.storage._hpe_smartstorage import build_drive_resource

        body = build_drive_resource(
            "/redfish/v1/Systems/1/Storage/0/Drives/1",
            {"Id": "1", "Oem": {"Hpe": {"Location": "Bay 1"}}},
        )
        self.assertEqual(body["Oem"]["Hpe"], {"Location": "Bay 1"})
        self.assertEqual(body["Oem"]["Redpool"]["HpeSmartStorage"]["Kind"], "DiskDrive")
        # The source payload is not embedded; its values are named properties.
        self.assertNotIn("Raw", body["Oem"]["Redpool"]["HpeSmartStorage"])


if __name__ == "__main__":
    unittest.main()


_CONTROLLER = "/redfish/v1/Systems/1/Storage/0/Controllers/0"
_BATTERY = {
    "ChargeLevelPercent": 99,
    "FirmwareVersion": "0.70",
    "Index": 1,
    "MaximumCapWatts": 96,
    "Model": "875241-B21",
    "ProductName": "HPE Smart Storage Battery ",
    "RemainingChargeTimeSeconds": 33,
    "SerialNumber": "DUMMY-SerialNumber",
    "SparePartNumber": "878643-001",
    "Status": {"Health": "OK", "State": "Enabled"},
}


def _battery(**overrides: object) -> dict:
    from normalizers.systems.storage._hpe_smartstorage import build_battery_resource

    return build_battery_resource(
        f"{_CONTROLLER}/Batteries/1", {**_BATTERY, **overrides}
    )


def test_hpe_battery_is_schema_valid() -> None:
    body = _battery()
    assert validate_document(body).status == "valid", validate_document(body).issues
    assert body["ChargeState"] is None
    assert "Links" not in body
    assert "StateOfHealthPercent" not in body


def test_hpe_battery_without_charge_time_has_no_charge_state() -> None:
    body = _battery(RemainingChargeTimeSeconds=0)
    assert body["ChargeState"] is None
    assert validate_document(body).status == "valid"


@pytest.mark.requires_fixtures
def test_hpe_logical_drive_volume_has_no_volume_type() -> None:
    body = _proxy_request("/redfish/v1/Systems/1/Storage/0/Volumes/1")
    assert "VolumeType" not in body
    result = validate_document(body)
    assert result.status == "valid", result.issues


def test_native_volumes_missing_from_logical_drives_are_kept(tmp_path):
    model = "ProLiant_DL380_Gen10"
    original = tmp_path / "HPE" / model / "original"
    system = "/redfish/v1/Systems/1"
    smart = f"{system}/SmartStorage"
    array = f"{smart}/ArrayControllers/0"
    native = f"{system}/Storage/native"
    resources = {
        "/redfish/v1": {"@odata.id": "/redfish/v1"},
        smart: {"@odata.id": smart},
        array: {"@odata.id": array, "Id": "0", "Model": "Test Array Controller"},
        f"{array}/LogicalDrives": {
            "Members": [{"@odata.id": f"{array}/LogicalDrives/1"}],
        },
        f"{array}/LogicalDrives/1": {
            "@odata.id": f"{array}/LogicalDrives/1",
            "@odata.type": "#HpeSmartStorageLogicalDrive.v2_0_0.HpeSmartStorageLogicalDrive",
            "Id": "1",
            "LogicalDriveName": "Test logical drive",
            "Raid": "RAID1",
        },
        f"{system}/Storage": {"Members": [{"@odata.id": native}]},
        native: {"@odata.id": native, "Name": "Test Array Controller"},
        f"{native}/Volumes": {
            "Members": [{"@odata.id": f"{native}/Volumes/{i}"} for i in ("1", "65")],
        },
        f"{native}/Volumes/65": {
            "@odata.id": f"{native}/Volumes/65",
            "@odata.type": "#Volume.v1_0_0.Volume",
            "Id": "65",
            "Name": "Test native volume",
            "RAIDType": "None",
            "CapacityBytes": 1_000_000,
            "Links": {"Drives": [{"@odata.id": f"{native}/Drives/0"}]},
        },
    }
    for uri, body in resources.items():
        path = original / uri.lstrip("/") / "index.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body), encoding="utf-8")

    volumes = f"{system}/Storage/0/Volumes"
    collection = _proxy_request(volumes, model, fixtures=tmp_path)
    assert collection["Members"] == [
        {"@odata.id": f"{volumes}/1"},
        {"@odata.id": f"{volumes}/65"},
    ]

    logical = _proxy_request(f"{volumes}/1", model, fixtures=tmp_path)
    assert logical["RAIDType"] == "RAID1"

    volume = _proxy_request(f"{volumes}/65", model, fixtures=tmp_path)
    assert volume["@odata.type"] == "#Volume.v1_10_0.Volume"
    assert volume["@odata.id"] == f"{volumes}/65"
    assert volume["RAIDType"] == "None"
    assert volume["CapacityBytes"] == 1_000_000
    assert volume["Links"]["Drives"] == [{"@odata.id": f"{system}/Storage/0/Drives/0"}]
