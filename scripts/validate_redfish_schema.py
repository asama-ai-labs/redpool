#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Validate normalized Redfish JSON against the DMTF schema submodule.

Reads ``@odata.type`` and checks the document against the matching file in
``third_party/Redfish-Publications/json-schema``. OEM types with no DMTF
schema are skipped. Exit status is 1 when any document is invalid.

Usage (from the repository root):

    uv run --extra dev python scripts/validate_redfish_schema.py
    uv run --extra dev python scripts/validate_redfish_schema.py --vendor Dell --model PowerEdge_R640
    uv run --extra dev python scripts/validate_redfish_schema.py path/to/resource.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from redpool.schema_validator import (
    deprecation_notes,
    is_dmtf_type_newer_than_bundle,
    iter_normalized_documents,
    redpool_oem_schema_available,
    schema_bundle_available,
    schema_dir,
    validate_file,
    validate_redpool_oem,
)

_PUBLIC = Path(__file__).resolve().parent.parent


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="JSON files to validate. Default: every fixtures normalized tree.",
    )
    parser.add_argument(
        "--vendor", help="Limit the fixtures walk to one vendor directory"
    )
    parser.add_argument(
        "--model", help="Limit the fixtures walk to one model directory"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Also fail when a document names a DMTF type at a version newer than the "
            "pinned bundle (the bundle is out of date, or a normalizer targets a version "
            "that does not exist)"
        ),
    )
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=_PUBLIC / "fixtures",
        help="Fixtures root (default: fixtures)",
    )
    return parser.parse_args()


def _documents(args: argparse.Namespace) -> list[Path]:
    if args.paths:
        return args.paths
    return list(
        iter_normalized_documents(args.fixtures, vendor=args.vendor, model=args.model)
    )


def main() -> int:
    args = _parse_args()
    if not schema_bundle_available():
        print(f"schema bundle not found at {schema_dir()}", file=sys.stderr)
        return 2
    paths = _documents(args)
    counts: Counter[str] = Counter()
    signatures: Counter[str] = Counter()
    oem_invalid = 0
    too_new: list[str] = []
    deprecated: Counter[str] = Counter()
    for path in paths:
        result = validate_file(path)
        counts[result.status] += 1
        if result.status == "skipped" and is_dmtf_type_newer_than_bundle(
            result.odata_type
        ):
            too_new.append(f"{path}: {result.odata_type}")
        if result.status in ("valid", "invalid"):
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                body = None
            for note in deprecation_notes(body):
                deprecated[note] += 1
        if redpool_oem_schema_available():
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                document = None
            oem_issues = validate_redpool_oem(document) if document is not None else ()
            if oem_issues:
                oem_invalid += 1
                print(f"{path}: Redpool.v1_0_0 Oem.Redpool")
                for issue in oem_issues:
                    print(f"  {issue.path}: {issue.message}")
        if result.status != "invalid":
            continue
        type_label = result.odata_type or "(no @odata.type)"
        print(f"{path}: {type_label}")
        for issue in result.issues:
            print(f"  {issue.path}: {issue.message}")
            signatures[f"{issue.path}: {issue.message}"] += 1
    print(
        f"checked={sum(counts.values())} valid={counts['valid']} "
        f"invalid={counts['invalid']} skipped={counts['skipped']}"
    )
    if signatures:
        print("top issues:")
        for signature, count in signatures.most_common(15):
            print(f"  {count:5d}  {signature}")
    print(f"redpool_oem_invalid={oem_invalid}")
    if too_new:
        print(f"newer_than_bundle={len(too_new)}")
        for line in too_new[:15]:
            print(f"  {line}")
    if deprecated:
        print("deprecated (report only):")
        for note, count in sorted(deprecated.items()):
            print(f"  {count:5d}  {note}")
    failed = bool(counts["invalid"] or oem_invalid)
    if args.strict and too_new:
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
