# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Trim LogEntry collections to a few distinct messages.

Each ``LogServices/*/Entries/`` directory keeps one file per message variety, then
at most ``max_varieties`` of those. The collection document's ``Members`` list is
updated to match. ``mirror``, when set, names a second file to drop with each
removed entry (the normalized copy, for the fixture script).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

INDEX = "index.json"
log = logging.getLogger("redfish_snapshot.log_entries")


def variety_key(obj: dict) -> tuple:
    """Key for deduplication: same Redfish or OEM message type."""
    et = str(obj.get("EntryType") or "")
    mid = obj.get("MessageId")
    if isinstance(mid, str) and mid.strip():
        return ("MessageId", et, mid.strip())
    oem_code = obj.get("OemLogEntryCode")
    if isinstance(oem_code, str) and oem_code.strip():
        return ("OemLogEntryCode", et, oem_code.strip())
    oem = obj.get("Oem")
    if isinstance(oem, dict):
        hpe = oem.get("Hpe")
        if isinstance(hpe, dict):
            klass, code = hpe.get("Class"), hpe.get("Code")
            if klass is not None or code is not None:
                return ("HpeClassCode", et, (klass, code))
        for _vendor, branch in oem.items():
            if not isinstance(branch, dict):
                continue
            for key in ("LenovoMessageID", "CommonEventID", "MessageId"):
                value = branch.get(key)
                if isinstance(value, str) and value.strip():
                    return (key, et, value.strip())
    msg = obj.get("Message")
    if isinstance(msg, str) and msg.strip():
        return ("Message", et, msg.strip()[:200])
    entry_id = obj.get("Id")
    return ("Id", et, str(entry_id) if entry_id is not None else "")


def _member_entry_id(member: dict) -> str | None:
    oid = member.get("@odata.id")
    if isinstance(oid, str) and oid.strip():
        path = oid.strip()
        if path.startswith("http"):
            path = urlparse(path).path or path
        return unquote(path.rstrip("/").split("/")[-1])
    entry_id = member.get("Id")
    if entry_id is not None:
        return str(entry_id)
    return None


def _write_json(path: Path, data: object, indent: int | None) -> None:
    if indent is None:
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(data, indent=indent, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def _drop(path: Path, dry_run: bool) -> None:
    if not path.exists():
        return
    if dry_run:
        log.debug("DRY remove %s", path)
        return
    path.unlink()
    parent = path.parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()


def _trim_collection(
    entries_dir: Path,
    max_varieties: int,
    dry_run: bool,
    indent: int | None,
    mirror: Callable[[Path], Path | None] | None,
) -> tuple[int, int]:
    """Return (removed entry files, kept entry files) for one Entries directory."""
    entry_files = sorted(
        child / INDEX for child in entries_dir.iterdir() if (child / INDEX).is_file()
    )
    if not entry_files:
        return 0, 0

    by_key: dict[tuple, Path] = {}
    for path in entry_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("skip unreadable %s: %s", path, exc)
            continue
        key = variety_key(data)
        if key not in by_key:
            by_key[key] = path

    sorted_keys = sorted(by_key.keys())
    if len(sorted_keys) > max_varieties:
        sorted_keys = sorted_keys[:max_varieties]

    keep_paths = {by_key[key] for key in sorted_keys}
    for path in entry_files:
        if path in keep_paths:
            continue
        if mirror is not None:
            extra = mirror(path)
            if extra is not None:
                _drop(extra, dry_run)
        _drop(path, dry_run)

    collection_json = entries_dir / INDEX
    if collection_json.is_file():
        try:
            coll = json.loads(collection_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("skip collection update %s: %s", collection_json, exc)
        else:
            keep_ids = {path.parent.name for path in keep_paths}
            members = coll.get("Members")
            if isinstance(members, list):
                kept = []
                for member in members:
                    if not isinstance(member, dict):
                        continue
                    member_id = _member_entry_id(member)
                    if member_id is not None and member_id in keep_ids:
                        kept.append(member)
                coll["Members"] = kept
                coll["Members@odata.count"] = len(kept)
                if dry_run:
                    log.info(
                        "DRY update %s Members %d -> %d",
                        collection_json,
                        len(members),
                        len(kept),
                    )
                else:
                    _write_json(collection_json, coll, indent)
            else:
                log.warning("no Members list in %s", collection_json)

    return len(entry_files) - len(keep_paths), len(keep_paths)


def entry_dirs(original_dir: Path) -> list[Path]:
    """``Entries`` directories under ``original_dir`` that hold at least one entry."""
    found: list[Path] = []
    for log_services in original_dir.rglob("LogServices"):
        if not log_services.is_dir():
            continue
        for child in sorted(log_services.iterdir()):
            entries = child / "Entries"
            if entries.is_dir() and any(
                (item / INDEX).is_file() for item in entries.iterdir()
            ):
                found.append(entries)
    return found


def trim_log_entries(
    original_dir: Path,
    *,
    max_varieties: int,
    dry_run: bool = False,
    indent: int | None = None,
    mirror: Callable[[Path], Path | None] | None = None,
) -> tuple[int, int]:
    """Trim every log collection under ``original_dir``.

    Returns (removed entry files, kept entry files). ``indent`` None writes
    compact JSON. ``mirror`` maps a removed ``index.json`` to another file to drop.
    """
    removed = kept = 0
    for entries in entry_dirs(original_dir):
        n_removed, n_kept = _trim_collection(
            entries, max_varieties, dry_run, indent, mirror
        )
        if n_removed or n_kept:
            log.info(
                "%s kept=%d removed=%d",
                entries.relative_to(original_dir),
                n_kept,
                n_removed,
            )
        removed += n_removed
        kept += n_kept
    return removed, kept
