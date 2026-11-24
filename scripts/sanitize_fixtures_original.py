#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Rewrite fixtures original fixtures and metadata through the shared sanitizer.

Does not touch normalized/. After this, regenerate that tree with
scripts/generate_normalized_outputs.py.

  uv run python scripts/sanitize_fixtures_original.py
  uv run python scripts/sanitize_fixtures_original.py --vendor Dell --model PowerEdge_R640

Each capture's collected identifiers are saved under $REDPOOL_SANITIZE_STATE (default
~/.cache/redpool-sanitize), which must be outside every git repository.

Add --mask-time to also shift timestamps, set zones to UTC, round manufacture and licence
dates and scale uptime counters. The shift comes from $REDPOOL_SANITIZE_SECRET and the
capture's name. Each capture records `time_policy` in its metadata.json and is skipped on
later runs.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "redfish-snapshot" / "src"))

from redfish_snapshot.postprocess import (  # noqa: E402
    SECRET_ENV,
    sanitize_mockups,
    state_dir,
)


def _matches(path: Path, fixtures: Path, vendor: str | None, model: str | None) -> bool:
    """True when path is under the optional vendor/model filter."""
    parts = path.relative_to(fixtures).parts
    if len(parts) < 2:
        return False
    if vendor and parts[0].lower() != vendor.lower():
        return False
    if model and parts[1].lower() != model.lower():
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", help="Only process this vendor")
    parser.add_argument("--model", help="Only process this model")
    parser.add_argument(
        "--mask-time",
        action="store_true",
        help="Also mask timestamps, time zones and counters (run once)",
    )
    args = parser.parse_args()
    secret = os.environ.get(SECRET_ENV, "")
    if args.mask_time and not secret:
        print(f"--mask-time needs ${SECRET_ENV} to be set", file=sys.stderr)
        return 2

    fixtures = REPO_ROOT / "fixtures"
    original_dirs = sorted(
        p
        for p in fixtures.glob("*/*/original")
        if _matches(p, fixtures, args.vendor, args.model)
    )
    metadatas = sorted(
        p
        for p in fixtures.glob("*/*/metadata.json")
        if _matches(p, fixtures, args.vendor, args.model)
    )
    if not original_dirs:
        print("No fixtures/*/*/original/ directories", file=sys.stderr)
        return 1

    changed, meta_changed, renamed = sanitize_mockups(
        original_dirs,
        metadatas,
        log=lambda msg: print(msg, file=sys.stderr),
        mask_time=args.mask_time,
        time_secret=secret.encode() or None,
        state=state_dir(),
    )
    print(
        f"Sanitized {len(original_dirs)} original tree(s), {changed} file(s) updated; "
        f"{meta_changed} metadata file(s); {renamed} path(s) renamed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
