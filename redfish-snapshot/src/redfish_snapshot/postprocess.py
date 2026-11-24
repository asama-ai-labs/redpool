# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Sanitize existing DMTF-layout mockups in place.

Works on any tree of Redfish JSON, such as ``redfish-snapshot clone`` output or
DMTF Redfish-Mockup-Creator output: every ``*.json`` body is sanitized, and
directory names that carry identifying tokens are renamed. One placeholder map
is built across all the trees given, so placeholders are stable between them.

Identifiers are handled one capture at a time. Each capture's real serials, MACs and
names are collected from its raw documents, merged with the list saved by earlier runs,
and then removed from every value, key, path and metadata string of that capture.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Callable, Iterable, Optional

from redfish_snapshot.sanitize import (
    IdentifierMasker,
    RedfishSanitizer,
    build_dirgroup_id_map,
    collect_identifiers,
    map_etags,
    sanitize_path,
    sanitize_redfish,
    sanitize_resource_tokens,
)
from redfish_snapshot.temporal import TIME_POLICY_VERSION, TemporalMasker

_DIRGROUP_RE = RedfishSanitizer.DIRGROUP_RE
STATE_ENV = "REDPOOL_SANITIZE_STATE"
SECRET_ENV = "REDPOOL_SANITIZE_SECRET"


def _compact(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _metadata_text(data: object, raw: str) -> str:
    """Preserve pretty-printed metadata; mockup documents stay compact."""
    match = re.search(r"\n( +)\"", raw)
    if match:
        return json.dumps(data, ensure_ascii=False, indent=len(match.group(1))) + "\n"
    return _compact(data) + "\n"


def _walk(
    obj: object, fn: Callable[[str], str], key_fn: Optional[Callable[[str], str]] = None
) -> object:
    """Apply *fn* to every string value, and *key_fn* to every dictionary key."""
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            new_key = key_fn(k) if key_fn else k
            if new_key != k and new_key in obj:
                new_key = k  # never overwrite a sibling
            out[new_key] = _walk(v, fn, key_fn)
        return out
    if isinstance(obj, list):
        return [_walk(v, fn, key_fn) for v in obj]
    if isinstance(obj, str):
        return fn(obj)
    return obj


def _remove_empty_dirs(root: Path) -> None:
    for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
        p = Path(dirpath)
        if p == root:
            continue
        try:
            p.rmdir()
        except OSError:
            pass


# --- saved identifier state -------------------------------------------------------------


def _inside_git_work_tree(path: Path) -> bool:
    return any((p / ".git").exists() for p in [path, *path.parents])


def state_dir() -> Path:
    """Where the real identifiers collected from captures are kept.

    ``$REDPOOL_SANITIZE_STATE``, or ``~/.cache/redpool-sanitize``. The directory holds every
    real identifier, so it must never be inside a git work tree.
    """
    path = Path(
        os.environ.get(STATE_ENV) or Path.home() / ".cache" / "redpool-sanitize"
    )
    path = path.expanduser().resolve()
    if _inside_git_work_tree(path):
        raise SystemExit(
            f"{path} is inside a git work tree. Set {STATE_ENV} to a directory outside "
            "every repository: it holds the real identifiers."
        )
    return path


def server_key(root: Path) -> str:
    """Name of a capture, for example ``Dell_PowerEdge_R640``, from its ``original/`` path."""
    return "_".join(root.resolve().parent.parts[-2:])


def _state_file(directory: Path, root: Path) -> Path:
    return directory / f"{server_key(root)}.identifiers.json"


def _load_state(directory: Path, root: Path) -> set[str]:
    try:
        return set(json.loads(_state_file(directory, root).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def _save_state(directory: Path, root: Path, identifiers: set[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    target = _state_file(directory, root)
    target.write_text(json.dumps(sorted(identifiers)) + "\n", encoding="utf-8")
    target.chmod(0o600)


# --- etags ------------------------------------------------------------------------------

_HASH_ALGORITHMS = {32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}
_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")


def _split_etag(value: str) -> tuple[str, str, str]:
    """(weak prefix, quote, core) of an etag value."""
    prefix = ""
    if value.startswith("W/"):
        prefix, value = "W/", value[2:]
    quote = ""
    if len(value) >= 2 and value[0] == value[-1] == '"':
        quote, value = '"', value[1:-1]
    return prefix, quote, value


def _hash_name(core: str) -> Optional[str]:
    """The hash an etag core is shaped like (hex of a known digest length), if any."""
    return _HASH_ALGORITHMS.get(len(core)) if _HEX_RE.match(core) else None


def _hexdigest(name: str, body: str) -> str:
    return hashlib.new(name, body.encode("utf-8"), usedforsecurity=False).hexdigest()


def _etag_like(value: str, digest: str) -> str:
    """A new etag with the same shape as *value*: prefix, quotes, length and character classes.

    Digits stay digits, lower-case letters stay lower-case, and so on. Only the characters
    change, drawn from *digest*, so a numeric Dell etag stays numeric.
    """
    prefix, quote, core = _split_etag(value)
    out = []
    for k, ch in enumerate(core):
        d = digest[k % len(digest)]
        if ch.isdigit():
            out.append(str(int(d, 16) % 10))
        elif "a" <= ch <= "z":
            out.append(chr(ord("a") + int(d, 16) % 26))
        elif "A" <= ch <= "Z":
            out.append(chr(ord("A") + int(d, 16) % 26))
        else:
            out.append(ch)
    return f"{prefix}{quote}{''.join(out)}{quote}"


def _strip_etags(data: object) -> object:
    blank = copy.deepcopy(data)
    map_etags(blank, lambda _value: "")
    return blank


def etag_verifies(value: object, body: str) -> bool:
    """True when a hash-shaped etag is the hash of *body* (the body without its etags)."""
    if not isinstance(value, str):
        return True
    _, _, core = _split_etag(value)
    name = _hash_name(core)
    return name is None or _hexdigest(name, body).lower() == core.lower()


def _etags_need_refresh(data: object) -> bool:
    """True when some hash-shaped etag is not the hash of its own document's body."""
    body = _compact(_strip_etags(data))
    found = []
    map_etags(data, lambda value: found.append(value) or value)
    return any(not etag_verifies(value, body) for value in found)


def _refresh_etags(data: object) -> None:
    """Re-derive each @odata.etag from the sanitized body, keeping its format.

    The etags BMCs send are hashes of the unsanitized body, so they let anyone brute-force
    masked values. A hash-shaped etag becomes the same hash of the sanitized body, so it
    verifies. Any other etag keeps its shape, with characters drawn from a digest.
    """
    body = _compact(_strip_etags(data))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

    def new_etag(value: object) -> object:
        if not isinstance(value, str):
            return value
        prefix, quote, core = _split_etag(value)
        name = _hash_name(core)
        if name is None:
            return _etag_like(value, digest)
        fresh = _hexdigest(name, body)
        fresh = fresh.upper() if core.isupper() else fresh
        return f"{prefix}{quote}{fresh}{quote}"

    map_etags(data, new_etag)


# --- paths ------------------------------------------------------------------------------


def _rename_changed_paths(root: Path, id_map: dict[str, str], mask_text) -> int:
    moves: list[tuple[Path, Path]] = []
    for src in root.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(root).as_posix()
        new_rel = mask_text(sanitize_path(rel, id_map=id_map))
        if new_rel != rel:
            moves.append((src, root / new_rel))
    moves.sort(key=lambda pair: len(pair[0].parts), reverse=True)
    renamed = 0
    for src, dest in moves:
        if not src.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise SystemExit(f"path collision: {src} -> {dest}")
        src.rename(dest)
        renamed += 1
    _remove_empty_dirs(root)
    return renamed


def _time_policy_applied(root: Path) -> bool:
    try:
        meta = json.loads((root.parent / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(meta, dict) and meta.get("time_policy") == TIME_POLICY_VERSION


def sanitize_mockups(
    roots: Iterable[Path],
    metadata_files: Iterable[Path] = (),
    log=print,
    mask_time: bool = False,
    time_secret: Optional[bytes] = None,
    state: Optional[Path] = None,
    extra_identifiers: Iterable[str] = (),
) -> tuple[int, int, int]:
    """Sanitize mockup trees in place.

    *metadata_files* (for example redfish-snapshot's ``metadata.json``) get path-token and
    identifier masking. Returns (documents changed, metadata files changed, paths renamed).

    *state* is a directory (see :func:`state_dir`) where each capture's collected identifiers
    are saved and merged with earlier runs. *extra_identifiers* are added to every capture's
    list, for example values a live capture collected before sanitizing.

    *mask_time* also masks time zones, timestamps and uptime counters. Each capture gets a
    shift derived from *time_secret* and its name, and a ``time_policy`` marker in its
    ``metadata.json``; a capture with the marker is skipped, so reruns change nothing.
    """
    roots = [Path(r) for r in roots]
    metadata_files = [Path(m) for m in metadata_files]
    if mask_time and not time_secret:
        raise ValueError("mask_time needs time_secret")

    tokens: set[str] = set()
    identifiers: dict[Path, set[str]] = {}
    for root in roots:
        found = set(extra_identifiers)
        for p in root.rglob("*.json"):
            try:
                raw = p.read_text(encoding="utf-8")
                tokens.update(_DIRGROUP_RE.findall(raw))
                found.update(collect_identifiers(json.loads(raw)))
            except (OSError, json.JSONDecodeError) as e:
                log(f"SKIP {p}: {e}")
            tokens.update(_DIRGROUP_RE.findall(p.relative_to(root).as_posix()))
        if state is not None:
            found |= _load_state(state, root)
            _save_state(state, root, found)
        identifiers[root] = found
        log(f"  {server_key(root)}: {len(found)} identifier(s)")
    for p in metadata_files:
        try:
            tokens.update(_DIRGROUP_RE.findall(p.read_text(encoding="utf-8")))
        except OSError as e:
            log(f"SKIP {p}: {e}")
    id_map = build_dirgroup_id_map(tokens)
    maskers = {
        root: IdentifierMasker(found, id_map=id_map)
        for root, found in identifiers.items()
    }

    # One time masker per capture, none for a capture that already has the marker.
    time_maskers: dict[Path, TemporalMasker] = {}
    if mask_time:
        for root in roots:
            if _time_policy_applied(root):
                log(f"  {server_key(root)}: time policy already applied, skipped")
                continue
            capture = "/".join(root.resolve().parent.parts[-2:])
            time_maskers[root] = TemporalMasker(time_secret, capture)
        for root in time_maskers:
            meta = root.parent / "metadata.json"
            if meta.is_file() and meta not in metadata_files:
                metadata_files.append(meta)

    doc_root = {p: root for root in roots for p in root.rglob("*.json")}
    documents = sorted(doc_root)
    changed = 0
    for i, p in enumerate(documents, start=1):
        try:
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            log(f"SKIP {p}: {e}")
            continue
        root = doc_root[p]
        masker = maskers[root]
        sanitized = _walk(
            sanitize_redfish(data, id_map=id_map), masker.mask, masker.mask_key
        )
        if root in time_maskers:
            sanitized = time_maskers[root].mask(sanitized)
        if _strip_etags(sanitized) == _strip_etags(data):
            # The body is as it was: keep its etag unless it hashes some other body.
            sanitized = data
            if _etags_need_refresh(sanitized):
                _refresh_etags(sanitized)
        else:
            _refresh_etags(sanitized)
        new_body = _compact(sanitized)
        if new_body != raw.rstrip("\n"):
            p.write_text(new_body + "\n", encoding="utf-8")
            changed += 1
        if i % 2000 == 0:
            log(f"  {i}/{len(documents)} documents")

    meta_changed = 0
    for p in metadata_files:
        try:
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError) as e:
            log(f"SKIP {p}: {e}")
            continue
        # metadata.json sits next to its capture's original/ tree.
        root = next((r for r in roots if r.parent == p.parent), None)
        masker = maskers.get(root) if root else None
        out = _walk(
            data,
            lambda s: (masker.mask if masker else str)(
                sanitize_path(s, id_map=id_map)
                if s.startswith("/redfish/")
                else sanitize_resource_tokens(s, id_map=id_map)
            ),
        )
        if root in time_maskers:
            if isinstance(out.get("collection_timestamp"), str):
                out["collection_timestamp"] = time_maskers[root].collection_date(
                    out["collection_timestamp"]
                )
            out["time_policy"] = TIME_POLICY_VERSION
        if out != data:
            p.write_text(_metadata_text(out, raw), encoding="utf-8")
            meta_changed += 1

    renamed = 0
    for root in roots:
        masker = maskers[root]
        shift = time_maskers[root].shift_path if root in time_maskers else str
        renamed += _rename_changed_paths(
            root, id_map, lambda text, m=masker, sh=shift: sh(m.mask(text))
        )
    return changed, meta_changed, renamed
