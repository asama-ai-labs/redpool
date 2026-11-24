# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""DMTF JSON Schema checks for Redfish documents."""

from __future__ import annotations

import pytest

from redpool.schema_validator import schema_bundle_available, validate_document

pytestmark = pytest.mark.skipif(
    not schema_bundle_available(),
    reason="Redfish-Publications or Swordfish-Publications submodule not checked out",
)


def _processor(**extra: object) -> dict:
    body = {
        "@odata.id": "/redfish/v1/Systems/1/Processors/CPU1",
        "@odata.type": "#Processor.v1_20_0.Processor",
        "Id": "CPU1",
        "Name": "Processor",
    }
    body.update(extra)
    return body


def test_minimal_processor_is_valid() -> None:
    result = validate_document(_processor())
    assert result.status == "valid"
    assert result.issues == ()


def test_unknown_property_is_rejected() -> None:
    result = validate_document(_processor(NotARealProperty=1))
    assert result.status == "invalid"
    assert any("NotARealProperty" in issue.message for issue in result.issues)


def test_enum_value_is_rejected() -> None:
    result = validate_document(_processor(ProcessorArchitecture="quantum"))
    assert result.status == "invalid"
    assert any(issue.path.endswith("ProcessorArchitecture") for issue in result.issues)


def test_invalid_date_time_is_rejected() -> None:
    result = validate_document(
        {
            "@odata.type": "#LogEntry.v1_16_1.LogEntry",
            "@odata.id": "/redfish/v1/Managers/1/LogServices/Log/Entries/1",
            "Id": "1",
            "Name": "Log Entry",
            "EntryType": "Event",
            "Created": "not-a-date",
        }
    )
    assert result.status == "invalid"
    assert any(issue.path.endswith("Created") for issue in result.issues)


def test_null_etag_is_rejected() -> None:
    result = validate_document(_processor(**{"@odata.etag": None}))
    assert result.status == "invalid"
    assert any("etag" in issue.path for issue in result.issues)


def test_collection_null_etag_reports_the_property() -> None:
    result = validate_document(
        {
            "@odata.type": "#ChassisCollection.ChassisCollection",
            "@odata.id": "/redfish/v1/Chassis",
            "@odata.etag": None,
            "Name": "Chassis Collection",
            "Members@odata.count": 0,
            "Members": [],
        }
    )
    assert result.status == "invalid"
    assert any("etag" in issue.path for issue in result.issues)
    assert all("Additional properties" not in issue.message for issue in result.issues)


def test_swordfish_ref_resolves() -> None:
    result = validate_document(
        {
            "@odata.type": "#ComputerSystem.v1_24_0.ComputerSystem",
            "@odata.id": "/redfish/v1/Systems/1",
            "Id": "1",
            "Name": "System",
            "HostedServices": {
                "StorageServices": {"@odata.id": "/redfish/v1/StorageServices"},
            },
        }
    )
    assert result.status == "valid", result.issues


def _volume(volume_type: str) -> dict:
    return {
        "@odata.type": "#Volume.v1_10_0.Volume",
        "@odata.id": "/redfish/v1/Systems/1/Storage/1/Volumes/1",
        "Id": "1",
        "Name": "Volume",
        "VolumeType": volume_type,
    }


def test_swordfish_enum_is_checked() -> None:
    bad = validate_document(_volume("Data"))
    assert bad.status == "invalid"
    assert any("VolumeType" in issue.path for issue in bad.issues)
    assert validate_document(_volume("RawDevice")).status == "valid"


def test_collection_member_link_is_valid() -> None:
    result = validate_document(
        {
            "@odata.type": "#ChassisCollection.ChassisCollection",
            "@odata.id": "/redfish/v1/Chassis",
            "Name": "Chassis Collection",
            "Members@odata.count": 1,
            "Members": [{"@odata.id": "/redfish/v1/Chassis/1"}],
        }
    )
    assert result.status == "valid", result.issues


def test_oem_type_is_skipped() -> None:
    result = validate_document(
        {
            "@odata.type": "#ContosoProcessor.v1_0_0.ContosoProcessor",
            "@odata.id": "/redfish/v1/Systems/1/Processors/1",
            "Id": "1",
            "Name": "Contoso",
        }
    )
    assert result.status == "skipped"
    assert result.detail == "no DMTF schema for this type"


def test_missing_odata_type_is_skipped() -> None:
    result = validate_document({"Id": "1"})
    assert result.status == "skipped"
