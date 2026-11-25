# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

from scripts.check_fixture_leaks import check_text


def test_checker_recognizes_numbered_macs_in_capture_formats():
    text = '["00:1B:44:AA:00:01", "MAC(001B44AA0002,0x1)", "ilo-001b44aa0003"]'
    assert list(check_text("index.json", text, None)) == []


def test_checker_flags_unmasked_macs_and_offset_in_path():
    text = '["12:34:56:78:9A:BC", "MAC(123456789ABC,0x1)", "ilo-123456789abc"]'
    path = "original/Reports/Report-2025-04-01T12:00:00+05:30/index.json"
    assert {check for check, _ in check_text(path, text, None)} == {
        "R-BYTERUN",
        "R-ILOMAC",
        "R-UEFIMAC",
        "S-TZ",
    }


def test_temporal_checks_detect_inconsistent_pairs_and_raw_epochs():
    from scripts.check_fixture_leaks import check_document

    doc = {
        "Container": [
            {
                "Timestamp": "01 Jan 2025, 11:25:00.000 PM",
                "TimestampWithTZ": "2024-02-01T06:05:01Z",
            }
        ],
        "Attributes": {"ServerPwrMon.1.MinPowerTime": "1740000000"},
    }
    assert set(check_document(doc, False)) == {
        ("S-TIME", "Timestamp/TimestampWithTZ"),
        ("S-TIME", "ServerPwrMon"),
    }


def test_epoch_log_ids_in_nested_entries_and_metadata_are_flagged():
    from scripts.check_fixture_leaks import check_document

    uri = "/redfish/v1/Systems/1/LogServices/EventLog/Entries"
    entry_id = "1769357212_1"
    doc = {"@odata.id": uri, "Members": [{"Id": entry_id}]}
    assert ("S-TIME", "epoch log entry Id") in set(check_document(doc, True))
    metadata = {"collected_urls": [f"{uri}/{entry_id}"]}
    assert set(check_document(metadata, False)) == {("S-TIME", "epoch log entry URL")}
