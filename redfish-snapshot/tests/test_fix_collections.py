# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""fix-collections on the DMTF mockup layout: <dir>/index.json, <dir>/<id>/index.json."""

import json
from pathlib import Path

from redfish_snapshot.collections import fix_collections_in_dir


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _member(uri: str) -> dict:
    return {"@odata.id": uri}


def test_members_without_a_saved_document_are_dropped(tmp_path):
    entries = tmp_path / "redfish" / "v1" / "Entries"
    _write(
        entries / "index.json",
        {
            "Members": [_member(f"/redfish/v1/Entries/{i}") for i in (1, 2, 3)],
            "Members@odata.count": 3,
            "Members@odata.nextLink": "/redfish/v1/Entries?$skip=3",
        },
    )
    _write(entries / "1" / "index.json", {"Id": "1"})
    _write(entries / "3" / "index.json", {"Id": "3"})

    assert fix_collections_in_dir(tmp_path) == 1

    fixed = json.loads((entries / "index.json").read_text(encoding="utf-8"))
    assert fixed["Members"] == [
        _member("/redfish/v1/Entries/1"),
        _member("/redfish/v1/Entries/3"),
    ]
    assert fixed["Members@odata.count"] == 2
    assert "Members@odata.nextLink" not in fixed


def test_collection_with_no_saved_members_is_left_alone(tmp_path):
    keys = tmp_path / "redfish" / "v1" / "Keys" / "index.json"
    _write(keys, {"Members": [], "Members@odata.count": 0})
    assert fix_collections_in_dir(tmp_path) == 0


def test_matching_collection_is_unchanged(tmp_path):
    coll = tmp_path / "redfish" / "v1" / "Systems"
    _write(
        coll / "index.json",
        {"Members": [_member("/redfish/v1/Systems/1")], "Members@odata.count": 1},
    )
    _write(coll / "1" / "index.json", {"Id": "1"})
    assert fix_collections_in_dir(tmp_path) == 0
