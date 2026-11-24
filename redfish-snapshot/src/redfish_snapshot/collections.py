# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Rewrite collection JSON so Members match the files on disk.

Works on the DMTF mockup layout: a collection is ``<dir>/index.json`` and each
member is ``<dir>/<id>/index.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

INDEX = "index.json"


def _member_id(m: dict) -> str | None:
    """Get member identifier from Id or last segment of @odata.id."""
    id_ = m.get("Id")
    if id_ is not None:
        return str(id_)
    odata = m.get("@odata.id") or ""
    if odata:
        return odata.rstrip("/").split("/")[-1]
    return None


def _write_json(path: Path, data: dict, compact_json: bool) -> None:
    """Write one JSON document, compact or indented."""
    with open(path, "w", encoding="utf-8") as handle:
        if compact_json:
            json.dump(data, handle, separators=(",", ":"), ensure_ascii=False)
        else:
            json.dump(data, handle, indent=2, ensure_ascii=False)


def _member_stub(member_dir: Path, member_id: str) -> dict:
    """Minimal member object when the collection entry itself is missing."""
    member_file = member_dir / member_id / INDEX
    try:
        with open(member_file, "r", encoding="utf-8") as handle:
            obj = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"@odata.id": "", "Id": member_id}
    return {"@odata.id": obj.get("@odata.id", ""), "Id": obj.get("Id", member_id)}


def _filtered_members(members: list, member_dir: Path, existing_ids: set[str]) -> list:
    """Members that still have a file, in sorted id order."""
    id_to_member = {}
    for member in members:
        mid = _member_id(member)
        if mid and mid in existing_ids:
            id_to_member[mid] = member
    filtered = []
    for mid in sorted(existing_ids):
        if mid in id_to_member:
            filtered.append(id_to_member[mid])
        else:
            filtered.append(_member_stub(member_dir, mid))
    return filtered


def _fix_collection_file(path: Path, dry_run: bool, compact_json: bool) -> bool:
    """Update one collection JSON to match on-disk members. Returns True if changed."""
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    members = data.get("Members")
    if not isinstance(members, list):
        return False

    member_dir = path.parent
    existing_ids = {
        entry.name for entry in member_dir.iterdir() if (entry / INDEX).is_file()
    }
    if not existing_ids:
        # No member was saved (empty collection, or members not captured).
        return False

    filtered = _filtered_members(members, member_dir, existing_ids)
    changed = False
    if data.get("Members@odata.count") != len(filtered):
        data["Members@odata.count"] = len(filtered)
        changed = True
    if data["Members"] != filtered:
        data["Members"] = filtered
        changed = True
    if "Members@odata.nextLink" in data:
        del data["Members@odata.nextLink"]
        changed = True

    if changed and not dry_run:
        _write_json(path, data, compact_json)
    return changed


def _find_collection_files(under: Path) -> list[Path]:
    """Find mockup documents under `under` that have a Members array."""
    out = []
    for j in sorted(under.rglob(INDEX)):
        if not j.is_file():
            continue
        try:
            with open(j, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("Members"), list):
                out.append(j)
        except (json.JSONDecodeError, OSError):
            continue
    return out


def fix_collections_in_dir(
    output_dir: Path,
    dry_run: bool = False,
    compact_json: bool = True,
    logger=None,
) -> int:
    """
    Fix collection JSON files under output_dir so Members and Members@odata.count
    match actual member files on disk. Removes Members@odata.nextLink.
    Returns number of files updated.
    """
    total = 0
    for path in _find_collection_files(output_dir):
        if _fix_collection_file(path, dry_run, compact_json):
            total += 1
            if logger:
                logger.info("Fixed collection: %s", path.relative_to(output_dir))
    return total
