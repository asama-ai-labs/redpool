#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Release check: fail when a fixture still holds an identifier a sanitizer should have removed.

  uv run python scripts/check_fixture_leaks.py [--fixtures fixtures] [--vendor V] [--model M]
                                               [--state DIR] [--json out.json]

Exit status 0 means no findings, 1 means findings. One line is printed per finding, with the
matched text cut to 6 characters so the report itself never carries a full identifier.

Checks, applied to every ``original/`` and ``normalized/`` file, ``metadata.json`` and ``.prom``:

  S-KNOWN  a real identifier saved by the sanitizer under --state (skipped without it)
  S-REGEX  the detector table below
  S-HEX    hex that decodes to serial-like text
  S-B64    base64 that decodes to serial-like text
  S-ETAG   a hash-shaped @odata.etag that is not the hash of its own document
  S-TZ     a time zone, or a UTC offset, that is not UTC
  S-LEAF   a key that must hold a placeholder but holds a value
  S-RESAN  a capture document, path or metadata URL that the current sanitizer would still
           change, so some rule was not applied (for example a capture made with
           --no-sanitize, or one sanitized before the rule existed)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "redfish-snapshot" / "src"))

from redfish_snapshot.postprocess import (  # noqa: E402
    _compact,
    _strip_etags,
    etag_verifies,
)
from redfish_snapshot.sanitize import (  # noqa: E402
    IdentifierMasker,
    RedfishSanitizer,
    sanitize_path,
    sanitize_redfish,
)

PLACEHOLDER_MACS = {RedfishSanitizer.DUMMY_MAC, RedfishSanitizer.DUMMY_WWN}

# id, pattern, optional predicate on the match (False means "not a finding")
DETECTORS = [
    ("R-IDRAC", r"(?i)\bidrac-[0-9A-Z]{7}\b", None),
    ("R-XCC", r"(?i)\bXCC-[0-9A-Z]{4}-[0-9A-Z]{6,}\b", None),
    ("R-HPESN", r"\bHPE_[A-Z0-9]{10}_", None),
    ("R-UEFISN", r"uefi-U\d+-[A-Z0-9]{8,}", None),
    ("R-SNHASH", r"SN#\s+(?!DUMMY)[A-Z0-9]{7,10}\b", None),
    ("R-SNPAREN", r"\((?:SN|SKU NO): (?!DUMMY)[^)]+\)", None),
    ("R-HSTNAME", r"HstName=(?!DUMMY)[^,\s]+", None),
    ("R-ST", r"\bST: (?!DUMMY)[0-9A-Z]{7}\b", None),
    ("R-SCVCN", r"Certificate (?!DUMMY)[0-9A-Z]{7}\b", None),
    ("R-NQN", r"PowerEdge\.R\d+\.(?!DUMMY)[0-9A-Z]{7}\b", None),
    ("R-UEFIMAC", r"MAC\((?!001B44AABBCC)[0-9A-Fa-f]{12}", None),
    ("R-ILOMAC", r"\bilo-(?!001b44aabbcc)[0-9a-f]{12}\b", None),
    (
        "R-BYTERUN",
        r"\b(?:[0-9A-Fa-f]{2}[ :-]){5,}[0-9A-Fa-f]{2}\b",
        lambda m: (
            m not in PLACEHOLDER_MACS and not set(m.replace(" ", "")) <= set("0:-")
        ),
    ),
    ("R-MACTAIL", r"00:1B:44:AA:BB:CC[:-](?!00:00\b)[0-9A-Fa-f]", None),
    ("R-LICID", r"\b(?:DLF|FD)\d{13,14}\b", None),
    ("R-TASKMON", r"/TaskMonitors?/(?!DUMMY)[A-Za-z0-9_-]{16,}", None),
    ("R-FODID", r"(?<![0-9A-Za-z])\d{2,5}-[0-9A-F]{16}(?![0-9A-Za-z])", None),
    ("R-OME", r"\bOME_(?!DUMMY)[0-9a-f]{12}\b", None),
    ("R-IKVM", r"/redfish/(?!DUMMY)[A-Za-z0-9]{10,}\.IKVM", None),
    (
        "R-UGUID",
        r"(?<![0-9A-Za-z])[0-9A-Fa-f]{8}(?:_[0-9A-Fa-f]{4}){3}_[0-9A-Fa-f]{12}",
        (lambda m: m.lower() != RedfishSanitizer.DUMMY_UUID.replace("-", "_")),
    ),
    ("R-LDNAME", r"\b[0-9A-F]{8}(?!DUMMYCONTROLLER)[A-Z0-9]{14} [0-9A-F]{4}\b", None),
    (
        "R-BOOTSN",
        r"\)\s+(?!DUMMY)[A-Z0-9]{10,20}\s+-|^UEFI \S+ \S+ (?!DUMMY)[A-Z0-9]{10,}\s*$",
        None,
    ),
    ("R-SSHKEY", r"ssh-(?:rsa|ed25519|dss) AAAA[0-9A-Za-z+/]{40,}", None),
    ("R-JID", r"(?<![0-9A-Za-z])(?:JID|RID)_(?!00000000)\d{12}(?![0-9A-Za-z])", None),
    (
        "R-SESSION",
        r"Sessions/DUMMY-User(0{6,}[0-9a-f]{8,})",
        lambda m: int(m, 16) >= 0x10000,
    ),
    (
        "R-CTIME",
        r"\b[A-Z][a-z]{2} [A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2} (?:UTC |GMT |)\d{4}",
        None,
    ),
    (
        "R-SWPORT",
        r'"(?:SwitchPortConnectionID|SwitchPortConnection|NIC\.1\.SwitchPortConnection)":"'
        r'(?!port-|No Link|DUMMY|Not )[^"]+"',
        None,
    ),
]
_COMPILED = [(i, re.compile(p, re.M), pred) for i, p, pred in DETECTORS]

# Keys whose values are placeholders after sanitizing.
LEAF_KEYS = frozenset(
    {
        "NodeID",
        "UniqueID",
        "ExpressServiceCode",
        "EntitlementID",
        "EntitlementId",
        "ProtectedIdentificationNumber",
        "ChipId",
        "PPID",
        "SystemConfigHash",
        "LogicalDriveName",
        "EngineID",
        "SNMPv3EngineID",
        "DUID",
        "SSHHostKey",
        "Signature",
        "iSCSIInitiatorName",
        "IscsiInitiatorName",
        "NvmeofHostDellNqn",
        "BackupFileLocation",
        "RecipientName",
        "ContactName",
        "ContactPerson",
        "LoginName",
        "Account",
        "AccountName",
    }
)
ZONE_KEYS = frozenset({"TimeZoneName", "Timezone", "DateTimeLocalOffset"})
SKIP_HEX_KEYS = frozenset(
    {
        "@odata.etag",
        "ETag",
        "Digest",
        "HashValue",
        "Hash",
        "SignatureString",
        "Thumbprint",
    }
)
DIGEST_LENGTHS = {32, 40, 64, 128}
OFFSET_RE = re.compile(r"\d{2}:\d{2}:\d{2}(?:\.\d+)?([+-]\d{2}:\d{2})")
HEX_RUN_RE = re.compile(
    r"(?<![0-9A-Za-z])(?:0[xX])?(?:[0-9A-Fa-f]{2}){6,}(?![0-9A-Za-z])"
    r"|(?<![0-9A-Za-z])(?:[0-9A-Fa-f]{2} ){5,}[0-9A-Fa-f]{2}(?![0-9A-Za-z])"
)
B64_RUN_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])")
PLACEHOLDER_LEAF = re.compile(
    r"^(DUMMY|0x0+[0-9a-f]*$|00( 00)+$|iqn\.2000-01\.invalid|$)"
)


def _short(value: str) -> str:
    return value[:6] + "…"


def _walk(obj, key=None):
    """Yield (key, string) for every string in a JSON value."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, key)
    elif isinstance(obj, str):
        yield key, obj


def _serial_like(blob: bytes) -> bool:
    """True when most of the bytes form one printable run that holds a letter and a digit."""
    best, cur = "", ""
    for byte in blob:
        if 0x21 <= byte <= 0x7E:
            cur += chr(byte)
            best = max(best, cur, key=len)
        else:
            cur = ""
    return (
        len(best) >= 6
        and len(best) >= len(blob) / 2
        and any(c.isalpha() for c in best)
        and any(c.isdigit() for c in best)
        and not best.startswith("DUMMY")
    )


def check_text(rel: str, text: str, masker: IdentifierMasker | None):
    """Checks that work on raw text: S-KNOWN and S-REGEX."""
    if masker is not None and (masker.mask(text) != text or masker.mask(rel) != rel):
        yield "S-KNOWN", "a saved identifier"
    for check_id, pattern, predicate in _COMPILED:
        for m in pattern.finditer(text):
            value = m.group(1) if m.lastindex else m.group(0)
            if predicate is None or predicate(value):
                yield check_id, _short(m.group(0))
                break


def _serial_token(blob: bytes) -> bool:
    """True when decoded bytes are mostly one alphanumeric token with both a letter and a digit."""
    tokens = re.findall(rb"[A-Za-z0-9]{6,}", blob)
    best = max(tokens, key=len, default=b"")
    return (
        len(best) >= 6
        and len(best) >= len(blob) / 2
        and any(chr(c).isalpha() for c in best)
        and any(chr(c).isdigit() for c in best)
        and not best.startswith(b"DUMMY")
    )


def check_document(data, is_original):
    """Checks that need the parsed document. S-ETAG applies to captures only: a normalized
    document copies its etag from the capture, whose body is public anyway."""
    body = _compact(_strip_etags(data))

    def etags(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "@odata.etag":
                    yield v
                else:
                    yield from etags(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from etags(v)

    for value in etags(data) if is_original else ():
        if not etag_verifies(value, body):
            yield "S-ETAG", _short(str(value))
    for key, value in _walk(data):
        leaf = key.rsplit(".", 1)[-1] if key else ""
        for pattern in RedfishSanitizer.USER_PATTERNS:
            for m in pattern.finditer(value):
                user = m.group(1).rstrip(".,;")
                if user not in RedfishSanitizer.USER_ALLOWLIST and not user.startswith(
                    "DUMMY"
                ):
                    yield "R-LOGUSER", _short(user)
        if leaf in LEAF_KEYS and not PLACEHOLDER_LEAF.match(value):
            yield "S-LEAF", f"{leaf}={_short(value)}"
        if leaf in ZONE_KEYS and value not in {"UTC", "+00:00", "Z", "GMT"}:
            yield "S-TZ", f"{leaf}={_short(value)}"
        for m in OFFSET_RE.finditer(value):
            if m.group(1) != "+00:00":
                yield "S-TZ", _short(value)
                break
        if key in SKIP_HEX_KEYS or leaf in SKIP_HEX_KEYS:
            continue
        for m in HEX_RUN_RE.finditer(value):
            digits = re.sub(r"^0[xX]|\s", "", m.group(0))
            if len(digits) in DIGEST_LENGTHS:
                continue
            try:
                blob = bytes.fromhex(digits)
            except ValueError:
                continue
            if _serial_like(blob):
                yield "S-HEX", _short(m.group(0))
                break
        if len(value) >= 24:
            for m in B64_RUN_RE.finditer(value):
                run = m.group(0)
                try:
                    blob = base64.b64decode(run + "=" * (-len(run) % 4), validate=True)
                except ValueError:
                    continue
                if _serial_token(blob):
                    yield "S-B64", _short(run)
                    break


def _changed_keys(a, b, key=""):
    """Keys (not values) where two JSON values differ."""
    if type(a) is not type(b):
        yield key
    elif isinstance(a, dict):
        for k in a.keys() | b.keys():
            if k not in a or k not in b:
                yield k
            else:
                yield from _changed_keys(a[k], b[k], k)
    elif isinstance(a, list):
        if len(a) != len(b):
            yield key
        else:
            for x, y in zip(a, b):
                yield from _changed_keys(x, y, key)
    elif a != b:
        yield key


def check_resanitize(rel: str, data):
    """S-RESAN: the current sanitizer leaves a sanitized capture unchanged."""
    if rel.startswith("original/"):
        tree_rel = rel[len("original/") :]
        if sanitize_path(tree_rel, id_map={}) != tree_rel:
            yield "S-RESAN", "<path>"
        for key in sorted(set(_changed_keys(data, sanitize_redfish(data, id_map={})))):
            yield "S-RESAN", str(key)[:40]
    elif rel == "metadata.json" and isinstance(data, dict):
        for url in data.get("collected_urls", []):
            if isinstance(url, str) and sanitize_path(url, id_map={}) != url:
                yield "S-RESAN", "collected_urls"
                break


def _server_files(server: Path):
    for pattern in (
        "original/**/*.json",
        "normalized/**/*.json",
        "metadata.json",
        "*.prom",
    ):
        for path in server.glob(pattern):
            if path.is_file():
                yield path


def _masker_for(state: Path | None, server: Path) -> IdentifierMasker | None:
    if state is None:
        return None
    saved = state / f"{server.parent.name}_{server.name}.identifiers.json"
    try:
        return IdentifierMasker(json.loads(saved.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def scan(fixtures: Path, vendor, model, state: Path | None):
    findings = []
    for server in sorted(fixtures.glob("*/*")):
        if not server.is_dir() or server.parent.name.startswith("."):
            continue
        if vendor and server.parent.name.lower() != vendor.lower():
            continue
        if model and server.name.lower() != model.lower():
            continue
        label = f"{server.parent.name}/{server.name}"
        masker = _masker_for(state, server)
        for path in _server_files(server):
            rel = path.relative_to(server).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            seen = set()
            results = list(check_text(rel, text, masker))
            if path.suffix == ".json":
                try:
                    data = json.loads(text)
                except ValueError:
                    data = None
                if data is not None:
                    results += list(check_document(data, rel.startswith("original/")))
                    results += list(check_resanitize(rel, data))
            for check_id, sample in results:
                if (check_id, sample) not in seen:
                    seen.add((check_id, sample))
                    findings.append((check_id, label, rel, sample))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=REPO_ROOT / "fixtures")
    parser.add_argument("--vendor")
    parser.add_argument("--model")
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(os.environ["REDPOOL_SANITIZE_STATE"])
        if os.environ.get("REDPOOL_SANITIZE_STATE")
        else None,
        help="Directory of saved identifiers (default: $REDPOOL_SANITIZE_STATE). "
        "Without it the S-KNOWN check is skipped.",
    )
    parser.add_argument("--json", type=Path, help="Also write the findings as JSON")
    args = parser.parse_args()

    findings = scan(args.fixtures, args.vendor, args.model, args.state)
    for check_id, label, rel, sample in findings:
        print(f"{check_id}  {label}  {rel}  {sample}")
    summary: dict[str, int] = {}
    for check_id, *_ in findings:
        summary[check_id] = summary.get(check_id, 0) + 1
    print(
        f"{len(findings)} finding(s)"
        + (
            ": " + ", ".join(f"{k} {v}" for k, v in sorted(summary.items()))
            if summary
            else ""
        )
        + ("" if args.state else " (S-KNOWN skipped: no --state)")
    )
    if args.json:
        args.json.write_text(
            json.dumps(
                [dict(zip(("check", "model", "path", "value"), f)) for f in findings],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
