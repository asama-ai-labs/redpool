# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Vendor selection happens in the registry; vendor aliases live in ``vendor_id``."""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import normalizers  # noqa: F401
from normalizers.managers.base import (
    _canonical_manager_manufacturer,
    _manager_manufacturer,
)
from normalizers.optional import OMIT
from normalizers.registry import get_resource_entry
from normalizers.systems.memory.dell_memory import DellMemoryNormalizer
from normalizers.systems.memory.hpe_memory import HPEMemoryNormalizer
from normalizers.types import NormalizationContext
from normalizers.vendor_id import canonical_server_vendor, manufacturer_from_model

_OLD_MANAGER_ALIASES = {
    "Dell": ("dell", "dell inc.", "dell inc", "dell technologies"),
    "HPE": (
        "hpe",
        "hpe inc.",
        "hewlett packard enterprise",
        "hewlett-packard enterprise",
        "hpeilo",
        "hp",
        "hpe, inc.",
        "hpe, inc",
    ),
    "Lenovo": ("lenovo", "lenovo group", "lenovo group limited"),
    "Supermicro": (
        "supermicro",
        "super micro",
        "supermicro computer",
        "supermicro computer, inc.",
        "supermicro computer inc.",
        "super micro computer",
    ),
}


@pytest.mark.parametrize(
    ("canonical", "alias"),
    [(c, a) for c, aliases in _OLD_MANAGER_ALIASES.items() for a in aliases],
)
def test_old_manager_aliases_still_resolve(canonical: str, alias: str) -> None:
    assert canonical_server_vendor(alias) == canonical
    assert canonical_server_vendor(alias.upper()) == canonical
    assert _canonical_manager_manufacturer({"Manufacturer": f" {alias} "}, oem={}) == (
        canonical
    )


def test_manager_unknown_vendor_passes_through_stripped() -> None:
    assert _canonical_manager_manufacturer({"Manufacturer": " Contoso "}, oem={}) == (
        "Contoso"
    )
    assert _canonical_manager_manufacturer({}, oem={}) is None


def test_dell_manager_manufacturer_uses_chassis_name() -> None:
    dell = NormalizationContext(
        data={"Manufacturer": "Dell"}, client=None, logger=MagicMock(), vendor="Dell"
    )
    assert _manager_manufacturer(dell) == "Dell Inc."
    assert manufacturer_from_model("PowerEdge R650") == "Dell Inc."
    assert canonical_server_vendor("Dell") == "Dell"
    assert canonical_server_vendor("Dell Inc.") == "Dell"


def test_hpe_manager_manufacturer_unchanged() -> None:
    hpe = NormalizationContext(
        data={"Manufacturer": "HPE"}, client=None, logger=MagicMock(), vendor="HPE"
    )
    assert _manager_manufacturer(hpe) == "HPE"


def _ctx(data: dict, vendor: str, model: str = "") -> NormalizationContext:
    return NormalizationContext(
        data=data, client=None, logger=MagicMock(), vendor=vendor, model=model
    )


def _memory_location(ctx: NormalizationContext):
    entry = get_resource_entry("Systems/Memory")
    value = entry.for_vendor(ctx.vendor).field_map()["MemoryLocation"](ctx)
    return None if value is OMIT else value


_HPE_BODY = {
    "MemoryLocation": {"Socket": 2, "MemoryController": 3, "Channel": 2, "Slot": 9}
}
_HPE_RESULT = {"Socket": 1, "MemoryController": 0, "Channel": 1, "Slot": 1}


def test_memory_location_routes_through_registered_vendor_normalizer() -> None:
    entry = get_resource_entry("Systems/Memory")
    assert isinstance(entry.for_vendor("Dell Inc."), DellMemoryNormalizer)
    assert isinstance(entry.for_vendor("HPE"), HPEMemoryNormalizer)
    assert _memory_location(
        _ctx({"Name": "DIMM A1"}, "Dell Inc.", "PowerEdge_R760")
    ) == {"Socket": 0, "MemoryController": 0, "Channel": 0, "Slot": 0}
    assert (
        _memory_location(_ctx(_HPE_BODY, "HPE", "ProLiant_DL360_Gen10")) == _HPE_RESULT
    )


def test_hp_vendor_gets_hpe_memory_mapping() -> None:
    assert (
        _memory_location(_ctx(_HPE_BODY, "HP", "ProLiant_DL360_Gen10")) == _HPE_RESULT
    )


def test_base_memory_has_no_vendor_branches() -> None:
    root = Path(__file__).resolve().parent.parent / "normalizers/systems/memory"
    loc = (root / "memory_location.py").read_text().lower()
    for vendor in ("supermicro", "hpe", "lenovo", "dell", "intel"):
        assert vendor not in loc
    for name in ("base.py", "memory_location.py"):
        tree = ast.parse((root / name).read_text())
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert "vendor" not in attrs, name
