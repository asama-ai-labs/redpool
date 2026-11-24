# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""DMTF schema names and HPE session ids must not be masked as hostnames."""

import json

from redfish_snapshot.postprocess import sanitize_mockups
from redfish_snapshot.sanitize import sanitize_redfish


def test_dmtf_schema_names_are_kept():
    doc = {
        "Location": [{"Uri": "/redfish/v1/schemas/redfish-schema-v1.json"}],
        "Id": "redfish-schema-v1",
        "Name": "redfish-schema-v1 JSON Schema File",
        "@odata.id": "/redfish/v1/JsonSchemas/redfish-payload-annotations.v1_1_1",
        "Schema": "#redfish-schema-v1.redfish-schema-v1",
    }
    assert sanitize_redfish(doc) == doc


def test_schema_locators_are_kept():
    for schema in (
        "#odata.v4_0_1.odata",
        "#odata.4.0.0.odata",
        "#redfish-error.v1_0_1.redfish-error",
        "#redfish-schema.v1_3_0.redfish-schema",
    ):
        assert sanitize_redfish({"Schema": schema}) == {"Schema": schema}


def test_real_hostnames_are_still_masked():
    out = sanitize_redfish(
        {
            "HostName": "bmc-rack-07",
            "Name": "my-bmc-host",
            "Message": "login from bmc01.corp.example-co.net",
        }
    )
    assert out["HostName"] == "DUMMY-HostName"
    assert out["Name"] == "DUMMY-HostName"
    assert "example-co" not in out["Message"]


def test_hpe_session_ids_lose_the_user_and_the_epoch_hex():
    sid = "test-ro0000000069c8ca2af6c8b43"
    out = sanitize_redfish(
        {
            "@odata.id": f"/redfish/v1/SessionService/Sessions/{sid}",
            "Id": sid,
            "UserName": "test-ro",
        }
    )
    # The hex tail is an epoch time, so it becomes a counter of the same width.
    new = "DUMMY-User" + "0" * 22 + "1"
    assert out["Id"] == new
    assert out["@odata.id"].endswith("/" + new)
    assert sanitize_redfish(out)["Id"] == new  # a second pass changes nothing


def test_hpe_session_mockup_is_renamed_consistently(tmp_path):
    sid = "administrator0000000068d3b6ca3eb850f"
    base = tmp_path / "redfish" / "v1" / "SessionService" / "Sessions"
    (base / sid).mkdir(parents=True)
    (base / "index.json").write_text(
        json.dumps(
            {
                "@odata.id": "/redfish/v1/SessionService/Sessions",
                "Oem": {
                    "Hpe": {
                        "Links": {
                            "MySession": {
                                "@odata.id": f"/redfish/v1/SessionService/Sessions/{sid}"
                            }
                        }
                    }
                },
                "Members": [
                    {"@odata.id": "", "Id": sid},
                    {"@odata.id": f"/redfish/v1/SessionService/Sessions/{sid}"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (base / sid / "index.json").write_text(
        json.dumps(
            {"@odata.id": f"/redfish/v1/SessionService/Sessions/{sid}", "Id": sid}
        ),
        encoding="utf-8",
    )

    sanitize_mockups([tmp_path], log=lambda _m: None)

    new = "DUMMY-User" + "0" * 22 + "1"
    assert (base / new / "index.json").is_file()
    assert not (base / sid).exists()
    text = (base / "index.json").read_text(encoding="utf-8")
    assert sid not in text and "administrator" not in text
    assert text.count(new) == 3
    assert json.loads((base / new / "index.json").read_text())["Id"] == new
