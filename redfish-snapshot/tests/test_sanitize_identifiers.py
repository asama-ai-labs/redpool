# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Distinct devices keep distinct placeholders; storage identifiers keep their format."""

from redfish_snapshot.sanitize import sanitize_redfish


def _drive(serial: str, durable: str) -> dict:
    return {
        "SerialNumber": serial,
        "Identifiers": [{"DurableName": durable, "DurableNameFormat": "NAA"}],
    }


def test_distinct_macs_stay_distinct_and_a_repeat_matches() -> None:
    id_map: dict = {}
    first = sanitize_redfish(
        {
            "MACAddress": "00:11:22:33:44:55",
            "PermanentMACAddress": "001122334455",
            "Note": "port 00-11-22-33-44-55",
        },
        id_map=id_map,
    )
    second = sanitize_redfish(
        {"MACAddress": "AA:BB:CC:DD:EE:FF"},
        id_map=id_map,
    )
    assert first["MACAddress"] == "00:1B:44:AA:00:01"
    assert first["PermanentMACAddress"] == "00:1B:44:AA:00:01"
    assert first["Note"] == "port 00:1B:44:AA:00:01"
    assert second["MACAddress"] == "00:1B:44:AA:00:02"
    assert sanitize_redfish(first, id_map={}) == first


def test_distinct_serials_get_distinct_placeholders_and_repeats_match() -> None:
    id_map: dict = {}
    a = sanitize_redfish(_drive("SN-TEST-0001", "NAA:60000000000000A5"), id_map=id_map)
    b = sanitize_redfish(_drive("SN-TEST-0002", "NAA:60000000000000A6"), id_map=id_map)
    again = sanitize_redfish(
        _drive("SN-TEST-0001", "NAA:60000000000000A5"), id_map=id_map
    )
    assert a["SerialNumber"] == "DUMMY-SerialNumber-1"
    assert b["SerialNumber"] == "DUMMY-SerialNumber-2"
    assert again == a


def test_durable_name_keeps_prefix_and_hex_width() -> None:
    id_map: dict = {}
    out = sanitize_redfish(_drive("X", "NAA:60000000000000A5"), id_map=id_map)
    name = out["Identifiers"][0]["DurableName"]
    assert name == "NAA:0000000000000001"
    assert "60000000000000A5" not in name


def test_distinct_durable_names_stay_distinct() -> None:
    id_map: dict = {}
    names = {
        sanitize_redfish(_drive("S", f"NAA:60000000000000A{i}"), id_map=id_map)[
            "Identifiers"
        ][0]["DurableName"]
        for i in range(8)
    }
    assert len(names) == 8


def test_volume_unique_identifier_is_masked_in_shape() -> None:
    unique = "6001405E8F2A1B0C3D4E5F60718293A4"
    out = sanitize_redfish({"VolumeUniqueIdentifier": unique}, id_map={})
    assert len(out["VolumeUniqueIdentifier"]) == len(unique)
    assert out["VolumeUniqueIdentifier"] != unique


def test_non_hex_durable_name_falls_back_to_a_numbered_dummy() -> None:
    out = sanitize_redfish(
        {"Identifiers": [{"DurableName": "device-name-with-dashes"}]}, id_map={}
    )
    assert out["Identifiers"][0]["DurableName"] == "DUMMY-DurableName-1"


def test_placeholders_are_left_alone() -> None:
    out = sanitize_redfish(_drive("DUMMY-SerialNumber-3", "DUMMY-NAA-1"), id_map={})
    assert out["SerialNumber"] == "DUMMY-SerialNumber-3"
    assert out["Identifiers"][0]["DurableName"] == "DUMMY-NAA-1"
