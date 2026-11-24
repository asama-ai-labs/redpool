# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""One resource type per port URI: ``Ports`` is #Port, ``NetworkPorts`` is #NetworkPort.

``NetworkPorts`` is deprecated and is served only where the BMC has it. Redpool never
rewrites it into ``Ports``, and never links a NetworkPorts collection the BMC lacks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_fixtures

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _normalized_files():
    if not _FIXTURES.is_dir():
        pytest.skip("fixtures submodule is not checked out")
    return sorted(
        _FIXTURES.glob(
            "*/*/normalized/redfish/v1/Chassis/*/NetworkAdapters/**/index.json"
        )
    )


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def test_port_documents_are_port_and_networkport_documents_are_networkport():
    checked = 0
    for f in _normalized_files():
        parts = f.parts
        if "Ports" not in parts and "NetworkPorts" not in parts:
            continue
        # Only member documents: .../NetworkAdapters/{id}/{Ports|NetworkPorts}/{member}/index.json
        i = max(
            parts.index("Ports") if "Ports" in parts else -1,
            parts.index("NetworkPorts") if "NetworkPorts" in parts else -1,
        )
        if i + 2 != len(parts) - 1:
            continue
        collection = parts[i]
        body = json.loads(f.read_text())
        otype = body.get("@odata.type") or ""
        checked += 1
        if collection == "Ports":
            assert otype.startswith("#Port."), f"{_rel(f, _FIXTURES)} is {otype}"
        else:
            assert otype.startswith("#NetworkPort."), f"{_rel(f, _FIXTURES)} is {otype}"
    assert checked > 0


def test_networkports_links_are_only_to_collections_the_bmc_has():
    """Redpool never invents a NetworkPorts link; Ports links may be served by a rewrite."""
    checked = 0
    for f in _normalized_files():
        body = json.loads(f.read_text())
        if not (body.get("@odata.type") or "").startswith("#NetworkAdapter."):
            continue
        checked += 1
        vendor, model = f.relative_to(_FIXTURES).parts[:2]
        model_dir = _FIXTURES / vendor / model
        link = body.get("NetworkPorts")
        if not isinstance(link, dict):
            continue
        oid = (link.get("@odata.id") or "").strip()
        if not oid:
            continue
        original = model_dir / "original" / Path(oid.lstrip("/")) / "index.json"
        assert original.is_file(), (
            f"{_rel(f, _FIXTURES)} links NetworkPorts {oid}, which the BMC capture does not have"
        )
    assert checked > 0
