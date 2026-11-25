# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Tests for HPE SmartStorage-only storage normalization."""

from __future__ import annotations

import unittest
from pathlib import Path

import pytest

from redpool.proxy import RedfishProxy, ServerMetadata
from redpool.schema_validator import validate_document
from scripts.mockup_server import mockup_redfish_client


def _proxy_request(path: str, model: str = "ProLiant_DL380_Gen10_2") -> dict:
    repo = Path(__file__).resolve().parent.parent
    model_dir = repo / "fixtures" / "HPE" / model
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

    @pytest.mark.requires_fixtures
    def test_native_volumes_missing_from_logical_drives_are_kept(self) -> None:
        collection = _proxy_request(
            "/redfish/v1/Systems/1/Storage/0/Volumes",
            model="ProLiant_DL380_Gen10",
        )
        self.assertEqual(
            [
                member["@odata.id"].rsplit("/", 1)[-1]
                for member in collection["Members"]
            ],
            ["1", "65", "69", "81", "85", "89", "93"],
        )

        logical = _proxy_request(
            "/redfish/v1/Systems/1/Storage/0/Volumes/1",
            model="ProLiant_DL380_Gen10",
        )
        self.assertEqual(logical["RAIDType"], "RAID1")

        native = _proxy_request(
            "/redfish/v1/Systems/1/Storage/0/Volumes/65",
            model="ProLiant_DL380_Gen10",
        )
        self.assertEqual(native["@odata.type"], "#Volume.v1_10_0.Volume")
        self.assertEqual(native["Id"], "65")
        self.assertEqual(native["RAIDType"], "None")
        self.assertEqual(native["CapacityBytes"], 1600321314816)
        self.assertEqual(
            native["Links"]["Drives"],
            [{"@odata.id": "/redfish/v1/Systems/1/Storage/0/Drives/0"}],
        )

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
