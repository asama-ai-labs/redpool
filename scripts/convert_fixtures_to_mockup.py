# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Convert fixtures from ``<parent>/<leaf>.json`` to the DMTF mockup layout.

The DMTF layout (Redfish-Mockup-Creator / Redfish-Mockup-Server) stores the
resource at URI ``/redfish/v1/<path>`` as ``redfish/v1/<path>/index.json``.

    original/service_root.json   ->  original/redfish/v1/index.json
    original/Systems.json        ->  original/redfish/v1/Systems/index.json
    original/Systems/1.json      ->  original/redfish/v1/Systems/1/index.json

Applies to ``original/`` and ``normalized/`` of every model. Files are moved,
not rewritten, so their bytes are unchanged. Run from the repository root:

    uv run python scripts/convert_fixtures_to_mockup.py
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def mockup_relpath(legacy: Path) -> Path:
    """Map a path relative to ``original/`` in the old layout to the new one."""
    if legacy == Path("service_root.json"):
        return Path("redfish/v1/index.json")
    return Path("redfish/v1") / legacy.with_suffix("") / "index.json"


def convert_tree(root: Path) -> int:
    """Convert one ``original/`` or ``normalized/`` directory in place."""
    if (root / "redfish" / "v1").is_dir():
        return 0  # already converted
    staging = root.with_name(root.name + ".mockup")
    if staging.exists():
        raise SystemExit(f"{staging} exists; remove it and rerun")
    sources = sorted(p for p in root.rglob("*") if p.is_file())
    others = [p for p in sources if p.suffix != ".json"]
    if others:
        raise SystemExit(f"non-JSON files under {root}: {others[:3]}")
    digests = {}
    for src in sources:
        dst = staging / mockup_relpath(src.relative_to(root))
        if dst.exists():
            raise SystemExit(f"two files map to {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        digests[dst] = hashlib.sha256(src.read_bytes()).hexdigest()
        src.rename(dst)
    for dst, digest in digests.items():
        if hashlib.sha256(dst.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"content changed while moving {dst}")
    shutil.rmtree(root)  # only empty directories remain
    staging.rename(root)
    return len(sources)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    args = parser.parse_args()
    total = 0
    for model_dir in sorted(args.fixtures.glob("*/*")):
        for name in ("original", "normalized"):
            tree = model_dir / name
            if tree.is_dir():
                total += convert_tree(tree)
    print(f"moved {total} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
