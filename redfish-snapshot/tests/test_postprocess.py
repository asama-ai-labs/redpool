# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""sanitize_mockups works on any DMTF-layout mockup, e.g. Redfish-Mockup-Creator output."""

import json

from redfish_snapshot.postprocess import sanitize_mockups


def test_mockup_documents_are_sanitized_in_place(tmp_path):
    system = tmp_path / "redfish" / "v1" / "Systems" / "1" / "index.json"
    system.parent.mkdir(parents=True)
    system.write_text(
        json.dumps({"Id": "1", "SerialNumber": "SN-TEST-0001", "Model": "R640"}),
        encoding="utf-8",
    )

    changed, _, _ = sanitize_mockups([tmp_path], log=lambda _msg: None)

    body = json.loads(system.read_text(encoding="utf-8"))
    assert changed == 1
    assert body["SerialNumber"] == "DUMMY-SerialNumber-1"
    assert body["Model"] == "R640"


def test_already_sanitized_mockup_is_unchanged(tmp_path):
    doc = tmp_path / "redfish" / "v1" / "index.json"
    doc.parent.mkdir(parents=True)
    doc.write_text('{"Id":"RootService"}\n', encoding="utf-8")
    assert sanitize_mockups([tmp_path], log=lambda _msg: None) == (0, 0, 0)
