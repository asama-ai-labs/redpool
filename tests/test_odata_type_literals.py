# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""A DMTF ``@odata.type`` is a string literal at its use site, never a constant or an f-string."""

from __future__ import annotations

import ast
import re
from pathlib import Path

NORMALIZERS = Path(__file__).resolve().parent.parent / "normalizers"

_DMTF_TYPE = re.compile(r"^#\w+\.v\d+_\d+_\d+\.\w+$")

# redpool_oem.py builds ``#<namespace>.Redpool<Owner>``, an OEM type outside the DMTF schema set.
_EXEMPT = {"redpool_oem.py"}


def _violations() -> list[str]:
    found: list[str] = []
    for path in sorted(NORMALIZERS.rglob("*.py")):
        if path.name in _EXEMPT:
            continue
        tree = ast.parse(path.read_text())
        rel = path.relative_to(NORMALIZERS.parent)
        for node in tree.body:
            value = None
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and _DMTF_TYPE.match(value.value)
            ):
                found.append(f"{rel}:{node.lineno} module constant {value.value}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.JoinedStr):
                continue
            literal = "".join(
                v.value
                for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
            has_formatting = any(isinstance(v, ast.FormattedValue) for v in node.values)
            if has_formatting and literal.startswith("#") and "." in literal:
                found.append(f"{rel}:{node.lineno} f-string type")
    return found


def test_odata_types_are_literals() -> None:
    assert _violations() == []


def test_hand_built_bodies_take_the_type_from_the_field_map() -> None:
    from normalizers.chassis.network_adapters.hpe_chassis_network_rewrite import (
        _physical_to_port,
        _synthesize_ports_from_adapter,
    )
    from normalizers.chassis.network_ports.base import prepare_port_document
    from normalizers.chassis.ports.base import (
        PORT_COLLECTION_MAPPING,
        BasePortNormalizer,
    )
    from normalizers.chassis.ports.dell import _port_collection, port_from_network_port
    from normalizers.systems.pci_devices.hpe import (
        build_synthetic_pcie_function_collection,
    )
    from normalizers.systems.pci_devices.pcie_functions.base import (
        COLLECTION_MAPPING as FUNCTION_COLLECTION_MAPPING,
    )

    port_type = BasePortNormalizer().field_map()["@odata.type"]
    collection_type = PORT_COLLECTION_MAPPING["@odata.type"]
    assert port_from_network_port({}, "/p")["@odata.type"] == port_type
    assert _port_collection({})["@odata.type"] == collection_type
    assert (
        prepare_port_document({"@odata.type": "#Port.v1_1_0.Port"})["@odata.type"]
        == port_type
    )
    assert _physical_to_port({}, "/a/Ports/1", 1)["@odata.type"] == port_type
    assert (
        _synthesize_ports_from_adapter({}, "/a/Ports")["@odata.type"] == collection_type
    )
    assert (
        build_synthetic_pcie_function_collection("/c", [])["@odata.type"]
        == FUNCTION_COLLECTION_MAPPING["@odata.type"]
    )
