#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Trim LogEntry fixtures to at most N files per LogServices/*/Entries/ directory.

The trim itself lives in redfish-snapshot. This command also removes the matching
files under normalized/. A new capture does this inside ``redfish-snapshot clone``.

After running, regenerate goldens for affected models with at least the same
``--max`` as ``--max-collection-sample`` so ``generate_normalized_outputs.py``
does not prune entries back down (default sample is 5).

  uv run python scripts/trim_log_entry_collections.py --dry-run
  uv run python scripts/trim_log_entry_collections.py
  uv run python scripts/generate_normalized_outputs.py --vendor Lenovo --model ThinkSystem_SR650_V2 --max-collection-sample 50
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "redfish-snapshot" / "src"))

from normalizers.url_rewrites import rewrite_path  # noqa: E402
from redfish_snapshot.log_entries import trim_log_entries  # noqa: E402
from redpool.mockup import relpath_to_uri, uri_to_relpath  # noqa: E402

log = logging.getLogger("trim_log_entries")

DEFAULT_MODELS = (
    "Lenovo/ThinkSystem_SR650_V2",
    "HPE/ProLiant_DL380_Gen10",
    "HPE/ProLiant_DL360_Gen10",
    "Dell/PowerEdge_R7525",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="*",
        default=list(DEFAULT_MODELS),
        help="Vendor/Model paths under fixtures/ (default: four large LogEntry fixtures)",
    )
    parser.add_argument(
        "--max", type=int, default=50, metavar="N", help="Max entries per collection"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    for vm in args.models:
        parts = vm.split("/", 1)
        if len(parts) != 2:
            log.error("bad model %r (want Vendor/Model)", vm)
            return 2
        vendor, model = parts
        model_dir = REPO_ROOT / "fixtures" / vendor / model
        original_dir = model_dir / "original"
        output_dir = model_dir / "normalized"
        if not original_dir.is_dir():
            log.warning("skip missing %s", original_dir)
            continue

        def mirror(
            entry: Path, original: Path = original_dir, normalized: Path = output_dir
        ) -> Path:
            uri = relpath_to_uri(entry.relative_to(original))
            return normalized / uri_to_relpath(rewrite_path(uri))

        removed, kept = trim_log_entries(
            original_dir,
            max_varieties=args.max,
            dry_run=args.dry_run,
            indent=2,
            mirror=mirror,
        )
        log.info("[%s] totals kept=%d removed=%d", vm, kept, removed)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
