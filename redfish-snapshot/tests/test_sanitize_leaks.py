# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Leak-review rules: identifiers hidden in other keys, encodings and free text."""

import json

from redfish_snapshot.postprocess import sanitize_mockups
from redfish_snapshot.sanitize import (
    IdentifierMasker,
    collect_identifiers,
    sanitize_redfish,
)


def _clean(doc):
    return sanitize_redfish(doc)


def test_device_id_leaves_are_replaced():
    out = _clean({"NodeID": "7FS1234", "EntitlementID": "ABC123", "ChipId": "CHIP99"})
    assert out == {
        "NodeID": "DUMMY-NodeID",
        "EntitlementID": "DUMMY-EntitlementID",
        "ChipId": "DUMMY-ChipId",
    }


def test_opaque_leaves_are_replaced_in_dotted_attribute_names():
    out = _clean({"Attributes": {"SNMP.1.EngineID": "0x80001f88041234"}})
    assert out["Attributes"]["SNMP.1.EngineID"] == "DUMMY-EngineID"


def test_asset_tag_protection_is_not_masked():
    out = _clean({"AssetTagProtection": "Enabled", "AssetTag": "ABC-123456"})
    assert out["AssetTagProtection"] == "Enabled"
    assert out["AssetTag"] != "ABC-123456"


def test_common_name_suffix_keys_are_masked():
    doc = {"SecurityCertificate": {"SubjectCommonName": "BS01U16CL01HVS1"}}
    assert _clean(doc)["SecurityCertificate"]["SubjectCommonName"] == "DUMMY-CommonName"


def test_vendor_common_name_is_kept():
    doc = {"SecurityCertificate": {"IssuerCommonName": "Dell Inc."}}
    assert _clean(doc)["SecurityCertificate"]["IssuerCommonName"] == "Dell Inc."


def test_hstname_in_platform_log_text_is_masked():
    out = _clean({"Message": "IP-Cfg:HstName=SPACMEDEPT, IPv4=10.1.2.3"})
    assert "SPACMEDEPT" not in out["Message"]
    assert "HstName=DUMMY-HostName" in out["Message"]


def test_component_serial_in_log_text_is_masked():
    out = _clean({"Message": "PSU1(SN: G2SZ47ABCD) failed; NVIDIA H100 (SN# 1A2B3C4D)"})
    assert "G2SZ47ABCD" not in out["Message"]
    assert "1A2B3C4D" not in out["Message"]


def test_uefi_device_path_mac_is_masked():
    out = _clean({"UefiDevicePath": "PciRoot(0x0)/MAC(001B44112233,0x1)"})
    assert "001B44112233" not in out["UefiDevicePath"]
    assert "MAC(001B44AA0001,0x1)" in out["UefiDevicePath"]


def test_space_separated_duid_is_masked():
    out = _clean({"Oem": {"Supermicro": {"DUID": "00 01 7C C2 55 12 34 56"}}})
    assert "7C C2 55" not in json.dumps(out)


def test_clock_time_is_not_an_ipv6_address():
    out = _clean({"Time": "Mon Jan 08 08:30:15 2018 UTC"})
    assert out["Time"] == "Mon Jan 08 08:30:15 2018 UTC"


def test_embedded_json_string_is_sanitized_and_stays_json():
    raw = json.dumps({"Licenses": [{"Signature": "abcdef123456", "Name": "x"}]})
    out = _clean({"LicenseManager": raw})["LicenseManager"]
    assert "abcdef123456" not in out
    assert json.loads(out)["Licenses"][0]["Signature"] == "DUMMY-Signature"


def test_fqdn_skip_tld_covers_efi_files():
    assert _clean({"Name": "shimx64.efi"})["Name"] == "shimx64.efi"


def test_collect_identifiers_takes_real_serials_only():
    doc = {
        "SerialNumber": "7FS1234",
        "ServiceTag": "DUMMY-ServiceTag-1",
        "Name": "CPU 1",
        "Oem": {"AssociatedNetworkAddresses": ["00:1B:44:11:22:33"]},
    }
    assert collect_identifiers(doc) == {"7FS1234", "00:1B:44:11:22:33"}


def test_identifier_masker_matches_separators_case_and_hex():
    masker = IdentifierMasker({"7FS-ABC123"})
    assert masker.mask("idrac-7fs abc123") == "idrac-DUMMY-ID-1"
    hex_form = "7FS-ABC123".encode().hex()
    assert masker.mask(f"NAA{hex_form}") == "NAADUMMY-ID-1"
    assert masker.mask("unrelated 7FS") == "unrelated 7FS"


def test_identifier_masker_without_identifiers_is_a_no_op():
    assert IdentifierMasker(set()).mask("7FS1234") == "7FS1234"


def test_sanitize_mockups_masks_serial_everywhere_and_refreshes_etags(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    doc = {
        "@odata.id": "/redfish/v1/Systems/1",
        "@odata.etag": 'W/"ORIGINAL-HASH"',
        "SerialNumber": "7FS1234",
        "Note": "tag 7FS-1234 seen in text",
    }
    (root / "Systems_1.json").write_text(json.dumps(doc), encoding="utf-8")
    (root / "7FS1234").mkdir()
    (root / "7FS1234" / "index.json").write_text("{}", encoding="utf-8")

    sanitize_mockups([root], log=lambda _msg: None)

    text = (root / "Systems_1.json").read_text(encoding="utf-8")
    assert "7FS" not in text
    out = json.loads(text)
    assert out["@odata.etag"] != 'W/"ORIGINAL-HASH"'
    assert out["@odata.etag"].startswith('W/"')
    assert len(out["@odata.etag"]) == len('W/"ORIGINAL-HASH"')
    assert not (root / "7FS1234").exists()


def test_etag_keeps_numeric_format():
    from redfish_snapshot.postprocess import _etag_like

    out = _etag_like("1715009483", "ab" * 32)
    assert out.isdigit() and len(out) == 10 and out != "1715009483"


def test_unchanged_document_keeps_its_etag(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    doc = {
        "@odata.id": "/redfish/v1/Chassis/1",
        "@odata.etag": "1715009483",
        "Name": "x",
    }
    (root / "Chassis_1.json").write_text(json.dumps(doc), encoding="utf-8")

    sanitize_mockups([root], log=lambda _msg: None)

    assert json.loads((root / "Chassis_1.json").read_text(encoding="utf-8")) == doc


def test_dummy_mac_is_never_collected_as_an_identifier():
    doc = {
        "MACAddress": "00:1B:44:AA:BB:CC",
        "PermanentMACAddress": "00:1B:44:AA:BB:CC",
    }
    assert collect_identifiers(doc) == set()


def test_real_mac_identifier_keeps_a_mac_shape():
    masker = IdentifierMasker({"00:1B:44:11:22:33"})
    assert masker.mask("MAC 00-1b-44-11-22-33 up") == "MAC 00:1B:44:AA:00:01 up"
    assert masker.mask("bare 001B44112233") == "bare 001B44AA0001"


def test_architecture_id_placeholder_matches_the_schema_pattern():
    import re

    out = _clean({"SNMP": {"EngineId": {"ArchitectureId": "58 43 43 2d 37 58 30 32"}}})
    value = out["SNMP"]["EngineId"]["ArchitectureId"]
    assert re.fullmatch(r"([A-Fa-f0-9]{2} ){0,27}[A-Fa-f0-9]{2}", value)
    assert value != "58 43 43 2d 37 58 30 32"


# --- time, zones and counters -------------------------------------------------------------

from redfish_snapshot.temporal import TemporalMasker  # noqa: E402


def _masker(capture="Vendor/Model"):
    return TemporalMasker(b"test-secret", capture)


def test_timestamps_move_by_one_shift_and_offsets_become_utc():
    m = _masker()
    a = m.mask({"A": "2025-04-01T12:00:00-05:00", "B": "2025-04-01T17:00:00Z"})
    # Same instant stays the same instant, and ordering and durations are kept.
    assert a["A"].endswith("+00:00") and a["B"].endswith("Z")
    assert a["A"][:-6] == a["B"][:-1]
    assert a["A"][:10] != "2025-04-01"


def test_fractions_survive_and_sentinels_are_left_alone():
    out = _masker().mask(
        {
            "T": "2025-04-01T12:00:00.459+00:00",
            "S": "1970-01-01T00:00:00Z",
            "E": "9999-12-31T23:59:59Z",
        }
    )
    assert out["T"].endswith(".459+00:00")
    assert out["S"] == "1970-01-01T00:00:00Z" and out["E"] == "9999-12-31T23:59:59Z"


def test_timestamp_inside_message_text_is_shifted_too():
    out = _masker().mask({"Message": "Logged at 2025-04-01T12:00:00Z by BMC"})
    assert "2025-04-01" not in out["Message"] and out["Message"].endswith(" by BMC")


def test_zones_and_local_offset_become_utc():
    out = _masker().mask(
        {
            "TimeZoneName": "Asia/Kolkata",
            "Time.1.Timezone": "CST6CDT",
            "DateTimeLocalOffset": "+05:30",
            "TimeZone": "UtcP530",
            "DateTime": {
                "TimeZone": {
                    "Index": 24,
                    "Name": "Chennai",
                    "UtcOffset": "+05:30",
                    "Value": "IST-5:30",
                }
            },
        }
    )
    assert out["TimeZoneName"] == "UTC" and out["Time.1.Timezone"] == "UTC"
    assert out["DateTimeLocalOffset"] == "+00:00" and out["TimeZone"] == "Utc0"
    assert out["DateTime"]["TimeZone"]["UtcOffset"] == "+00:00"


def test_manufacture_date_rounds_to_month_and_licence_dates_to_year():
    out = _masker().mask(
        {
            "ProductionDate": "2024-04-17T13:45:09Z",
            "LicenseSoldDate": "2025-09-16T08:00:00+00:00",
        }
    )
    assert out["ProductionDate"].endswith("-01T00:00:00Z")
    assert out["LicenseSoldDate"].endswith("-01-01T00:00:00+00:00")


def test_dates_damaged_by_the_old_ipv6_bug_keep_only_the_year():
    out = _masker().mask(
        {"ValidFrom": "Mon Jan 10 ::1 2022 UTC", "Timestamp": "17 Nov 2025, ::1.000 AM"}
    )
    assert out["ValidFrom"] == "Jan 1 ::1 2022 UTC"
    assert out["Timestamp"] == "1 Jan 2025, ::1.000 AM"


def test_uptime_counters_are_scaled_within_the_range_and_zero_stays_zero():
    out = _masker().mask({"PowerOnHours": 10000, "NumberOfReboots": 0, "Other": 10000})
    assert 8500 <= out["PowerOnHours"] <= 11400
    assert out["NumberOfReboots"] == 0 and out["Other"] == 10000


def test_shift_is_keyed_by_secret_and_capture_name():
    a, b = _masker("A/One"), _masker("A/Two")
    assert a.shift == _masker("A/One").shift  # the same on every run
    assert a.shift != b.shift
    assert a.shift != TemporalMasker(b"other-secret", "A/One").shift


def test_epoch_ids_are_shifted_in_ids_and_paths_and_keep_their_width():
    m = _masker()
    doc = {"Id": "1770197870841350", "Capacity": "1770197870841350"}
    out = m.mask(doc)
    assert len(out["Id"]) == 16 and out["Id"] != "1770197870841350"
    assert out["Capacity"] == "1770197870841350"  # only Id-like keys are shifted
    assert m.shift_path("Entries/1770197870841350") == "Entries/" + out["Id"]
    assert (
        m.shift_path("Entries/1000000000000") == "Entries/1000000000000"
    )  # not an epoch


def test_collection_date_is_a_shifted_date_without_time():
    out = _masker().collection_date("2026-10-28T10:26:53.069178")
    assert len(out) == 10 and out != "2026-10-28"


# --- smaller leak rules -------------------------------------------------------------------


def test_underscore_guid_is_masked():
    out = _clean(
        {"Boot": "HD(1,GPT,D9A45241_8A65_47A8_BBDA_0E9C8611FA35)/shimx64.efi"}
    )["Boot"]
    assert "D9A45241" not in out


def test_fod_key_id_and_bytes_are_masked():
    out = _clean({"Id": "52-3C18A4EBBB0556B4", "Bytes": [2, 68, 0, 55, 90]})
    assert out["Id"].startswith("DUMMY-FoDKey-") and out["Bytes"] == []


def test_switch_port_names_are_masked_but_link_states_are_kept():
    out = _clean(
        {
            "A": {"SwitchPortConnectionID": "fa2/0/35"},
            "B": {"SwitchPortConnectionID": "No Link"},
        }
    )
    assert out["A"]["SwitchPortConnectionID"] == "DUMMY-Port"
    assert out["B"]["SwitchPortConnectionID"] == "No Link"


def test_mask_time_option_shifts_documents_and_metadata(tmp_path):
    root = tmp_path / "model" / "original"
    root.mkdir(parents=True)
    (root / "a.json").write_text(
        json.dumps({"Time": "2025-04-01T12:00:00Z"}), encoding="utf-8"
    )
    meta = tmp_path / "model" / "metadata.json"
    meta.write_text(
        json.dumps({"collection_timestamp": "2025-04-01T12:00:00.5"}), encoding="utf-8"
    )

    sanitize_mockups(
        [root], [meta], log=lambda _m: None, mask_time=True, time_secret=b"k"
    )

    assert json.loads((root / "a.json").read_text())["Time"][:10] != "2025-04-01"
    stamp = json.loads(meta.read_text())["collection_timestamp"]
    assert len(stamp) == 10 and stamp != "2025-04-01"


def test_time_policy_marker_makes_a_rerun_change_nothing(tmp_path):
    root = tmp_path / "Vendor" / "Model" / "original"
    root.mkdir(parents=True)
    (root / "a.json").write_text(
        json.dumps({"Time": "2025-04-01T12:00:00Z"}), encoding="utf-8"
    )
    meta = root.parent / "metadata.json"
    meta.write_text(
        json.dumps({"collection_timestamp": "2025-04-01"}), encoding="utf-8"
    )
    run = dict(mask_time=True, time_secret=b"k", log=lambda _m: None)

    sanitize_mockups([root], [meta], **run)
    first = (root / "a.json").read_text(), meta.read_text()
    sanitize_mockups([root], [meta], **run)

    assert ((root / "a.json").read_text(), meta.read_text()) == first
    assert json.loads(meta.read_text())["time_policy"] == 1


def test_mask_time_without_a_secret_is_refused(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        sanitize_mockups([tmp_path], mask_time=True, log=lambda _m: None)


# --- etags --------------------------------------------------------------------------------


def _doc_with_etag(etag, **fields):
    return {"@odata.id": "/redfish/v1/X", "@odata.etag": etag, **fields}


def test_hash_shaped_etag_is_recomputed_so_it_verifies(tmp_path):
    from redfish_snapshot.postprocess import _compact, _strip_etags, etag_verifies

    root = tmp_path / "original"
    root.mkdir()
    # A body that is already clean, with an etag that hashes some other (unmasked) body.
    stale = "d41d8cd98f00b204e9800998ecf8427e"
    doc = _doc_with_etag(f'"{stale}"', Name="Clean")
    (root / "x.json").write_text(json.dumps(doc), encoding="utf-8")

    sanitize_mockups([root], log=lambda _m: None)

    out = json.loads((root / "x.json").read_text())
    assert out["@odata.etag"] != f'"{stale}"'
    assert out["@odata.etag"].startswith('"') and len(out["@odata.etag"]) == 34
    assert etag_verifies(out["@odata.etag"], _compact(_strip_etags(out)))


def test_short_opaque_etag_of_an_unchanged_document_is_kept(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    doc = _doc_with_etag("1715009483", Name="Clean")
    (root / "x.json").write_text(json.dumps(doc), encoding="utf-8")
    sanitize_mockups([root], log=lambda _m: None)
    assert json.loads((root / "x.json").read_text()) == doc


def test_etag_refresh_is_stable_on_a_second_run(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    doc = _doc_with_etag('"' + "a" * 128 + '"', Name="Clean")
    (root / "x.json").write_text(json.dumps(doc), encoding="utf-8")
    sanitize_mockups([root], log=lambda _m: None)
    first = (root / "x.json").read_text()
    sanitize_mockups([root], log=lambda _m: None)
    assert (root / "x.json").read_text() == first


# --- organisation and account names, per-server state, encodings --------------------------


def test_recipient_and_account_names_are_collected():
    doc = {
        "Recipients": {"RecipientName": "Acmecorp-Labs", "ContactName": "root"},
        "Oem": {"LoginName": "automation7"},
    }
    assert collect_identifiers(doc) == {"Acmecorp-Labs", "automation7"}


def test_organisation_name_is_removed_from_log_text_of_the_same_capture(tmp_path):
    root = tmp_path / "Vendor" / "Model" / "original"
    root.mkdir(parents=True)
    (root / "r.json").write_text(
        json.dumps({"RecipientName": "Acmecorp-Labs"}), encoding="utf-8"
    )
    (root / "log.json").write_text(
        json.dumps({"Message": "Mail sent to Acmecorp-Labs relay"}), encoding="utf-8"
    )
    sanitize_mockups([root], log=lambda _m: None)
    assert "Acmecorp" not in (root / "log.json").read_text()


def test_identifiers_are_kept_per_capture_not_pooled(tmp_path):
    one = tmp_path / "A" / "One" / "original"
    two = tmp_path / "A" / "Two" / "original"
    for root, serial in ((one, "ABC1234"), (two, "XYZ9876")):
        root.mkdir(parents=True)
        (root / "s.json").write_text(
            json.dumps({"SerialNumber": serial}), encoding="utf-8"
        )
    (two / "note.json").write_text(
        json.dumps({"Message": "see ABC1234"}), encoding="utf-8"
    )

    sanitize_mockups([one, two], log=lambda _m: None)

    # ABC1234 belongs to capture One only, so Two's text is left as it was.
    assert "ABC1234" in (two / "note.json").read_text()


def test_state_file_keeps_identifiers_for_the_next_run(tmp_path):
    root = tmp_path / "Vendor" / "Model" / "original"
    root.mkdir(parents=True)
    (root / "s.json").write_text(
        json.dumps({"SerialNumber": "ABC1234"}), encoding="utf-8"
    )
    state = tmp_path / "state"
    sanitize_mockups([root], state=state, log=lambda _m: None)
    # The serial is gone from the capture, but a later document that still carries it is caught.
    (root / "later.json").write_text(
        json.dumps({"Message": "tag abc-1234 seen"}), encoding="utf-8"
    )
    sanitize_mockups([root], state=state, log=lambda _m: None)
    assert "1234" not in (root / "later.json").read_text()
    assert (state / "Vendor_Model.identifiers.json").stat().st_mode & 0o077 == 0


def test_state_directory_inside_a_git_work_tree_is_refused(tmp_path, monkeypatch):
    import pytest

    from redfish_snapshot.postprocess import state_dir

    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("REDPOOL_SANITIZE_STATE", str(tmp_path / "state"))
    with pytest.raises(SystemExit):
        state_dir()


def test_identifier_in_a_dictionary_key_is_masked(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    (root / "a.json").write_text(
        json.dumps(
            {"SerialNumber": "ABC1234", "Attributes": {"Slot.ABC1234.Mode": "on"}}
        ),
        encoding="utf-8",
    )
    sanitize_mockups([root], log=lambda _m: None)
    assert "ABC1234" not in (root / "a.json").read_text()


def test_hex_and_base64_runs_holding_an_identifier_are_replaced_whole():
    import base64

    masker = IdentifierMasker({"ABC1234"})
    hex_run = "0x80001f8804" + "ABC1234".encode().hex()
    assert masker.mask(f"id {hex_run} end") == "id DUMMY-Encoded end"
    b64 = base64.b64encode(b"serial ABC1234 seen here").decode()
    assert masker.mask(f"blob {b64}") == "blob DUMMY-Encoded"
    assert (
        masker.mask("a1b2c3d4e5f6a7b8c9d0") == "a1b2c3d4e5f6a7b8c9d0"
    )  # nothing inside


# --- remaining rule variants ---------------------------------------------------------------


def test_dell_job_ids_become_stable_counters_and_stay_stable():
    doc = {
        "Id": "JID_123456789012",
        "@odata.id": "/redfish/v1/Jobs/JID_123456789012",
        "R": "RID_210987654321",
    }
    out = _clean(doc)
    assert out["Id"] == "JID_000000000001" and out["@odata.id"].endswith(
        "JID_000000000001"
    )
    assert out["R"] == "RID_000000000001"
    assert sanitize_redfish(out) == out


def test_fod_key_identifier_is_masked_and_collected():
    doc = {
        "@odata.type": "#LenovoFoDKey.v1_0_0.LenovoFoDKey",
        "Identifier": "7Z71-J9009026-A",
    }
    assert _clean(doc)["Identifier"].startswith("DUMMY-Identifier-")
    assert collect_identifiers(doc) == {"7Z71-J9009026-A"}


def test_drive_and_controller_serials_in_boot_strings_are_masked():
    lenovo = "UEFI:   SLOT 34 (5/0/0) S665NN0X50ABCD     -SAMSUNG MZ1L2960HCJR"
    intel = "UEFI ADATA SU650NS38 2L5029A8ABCD "
    hpe = "008D7AB3PEYHB0ABCDEFGH BBEF"
    out = _clean({"Boot": [lenovo, intel], "Name": hpe})
    assert "S665NN0X50ABCD" not in out["Boot"][0] and "SAMSUNG" in out["Boot"][0]
    assert "2L5029A8ABCD" not in out["Boot"][1] and "SU650NS38" in out["Boot"][1]
    assert "PEYHB0ABCDEFGH" not in out["Name"] and out["Name"].startswith("008D7AB3")


def test_log_user_names_are_masked_except_the_allowlist():
    doc = {
        "Message": "Unable to log in for jdoe from 192.0.2.1 using GUI.",
        "MessageArgs": ["jdoe", "GUI"],
    }
    out = _clean(doc)
    assert "jdoe" not in json.dumps(out) and "using GUI." in out["Message"]
    assert out["MessageArgs"] == ["DUMMY-User", "GUI"]
    assert (
        _clean({"Message": "changed by user root."})["Message"]
        == "changed by user root."
    )


def test_ikvm_token_is_masked_in_any_string_and_switch_attribute_is_masked():
    out = _clean(
        {
            "X": "see /redfish/AbCdEf123456.IKVM now",
            "NIC.1.SwitchPortConnection": "fa2/0/35",
        }
    )
    assert "AbCdEf123456" not in out["X"]
    assert out["NIC.1.SwitchPortConnection"] == "DUMMY-Port"


def test_sentinel_timestamps_keep_their_value_but_lose_the_site_offset():
    out = _masker().mask(
        {
            "DateTime": "1998-08-24T11:20:43-05:00",
            "Max": "9999-12-31T23:59:59Z",
            "Zero": "0000-00-00T00:00:00+00:00",
        }
    )
    assert out["DateTime"] == "1998-08-24T11:20:43+00:00"
    assert out["Max"] == "9999-12-31T23:59:59Z"
    assert out["Zero"] == "0000-00-00T00:00:00+00:00"


def test_sanitizer_placeholders_are_never_collected_as_identifiers():
    doc = {
        "@odata.type": "#LenovoFoDKey.v1_0_0.LenovoFoDKey",
        "Identifier": "DUMMY-Identifier-1",
        "RecipientName": "DUMMY-User",
        "SerialNumber": "DUMMY-SerialNumber-3",
    }
    assert collect_identifiers(doc) == set()
