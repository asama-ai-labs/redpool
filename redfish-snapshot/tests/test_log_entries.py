# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Log collections keep one file per message variety, then at most N of those."""

import json
from pathlib import Path

from redfish_snapshot.log_entries import trim_log_entries


def _entry(directory: Path, entry_id: str, message_id: str) -> None:
    folder = directory / entry_id
    folder.mkdir(parents=True)
    (folder / "index.json").write_text(
        json.dumps({"Id": entry_id, "MessageId": message_id, "Message": message_id}),
        encoding="utf-8",
    )


def test_trim_keeps_one_file_per_variety_and_updates_members(tmp_path: Path) -> None:
    entries = tmp_path / "LogServices" / "Log1" / "Entries"
    entries.mkdir(parents=True)
    _entry(entries, "1", "SEL.1.0.Assert")
    _entry(entries, "2", "SEL.1.0.Assert")
    _entry(entries, "3", "SEL.1.0.Deassert")
    (entries / "index.json").write_text(
        json.dumps(
            {
                "Members": [
                    {"@odata.id": "/redfish/v1/LogServices/Log1/Entries/1"},
                    {"@odata.id": "/redfish/v1/LogServices/Log1/Entries/2"},
                    {"@odata.id": "/redfish/v1/LogServices/Log1/Entries/3"},
                ],
                "Members@odata.count": 3,
            }
        ),
        encoding="utf-8",
    )
    mirror_root = tmp_path / "normalized"
    mirrored = mirror_root / "2" / "index.json"
    mirrored.parent.mkdir(parents=True)
    mirrored.write_text("{}", encoding="utf-8")

    removed, kept = trim_log_entries(
        tmp_path,
        max_varieties=1,
        mirror=lambda path: mirror_root / path.parent.name / "index.json",
    )

    assert (removed, kept) == (2, 1)
    assert (entries / "1" / "index.json").is_file()
    assert not (entries / "2").exists()
    assert not (entries / "3").exists()
    assert not mirrored.exists()
    collection = json.loads((entries / "index.json").read_text(encoding="utf-8"))
    assert collection["Members@odata.count"] == 1
    assert collection["Members"] == [
        {"@odata.id": "/redfish/v1/LogServices/Log1/Entries/1"}
    ]
