# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""The published Redpool OEM schema: valid itself, applied to every block, and the only casing."""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

from normalizers._shared.redpool_oem import stamp_redpool_oem_types
from redpool.schema_validator import (
    _REDPOOL_OEM_SCHEMA_PATH,
    iter_normalized_documents,
    validate_redpool_oem,
)

PUBLIC = Path(__file__).resolve().parents[1]
FIXTURES = PUBLIC / "fixtures"
NORMALIZERS = PUBLIC / "normalizers"
GENERATOR = PUBLIC / "scripts" / "generate_redpool_oem_schema.py"


def _schema() -> dict:
    return json.loads(_REDPOOL_OEM_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_schema_is_valid_draft7() -> None:
    jsonschema.Draft7Validator.check_schema(_schema())


def test_schema_defines_the_resources_redpool_writes() -> None:
    names = set(_schema()["definitions"])
    for expected in (
        "RedpoolChassis",
        "RedpoolStorageController",
        "RedpoolLogEntry",
        "HpeSmartStorage",
    ):
        assert expected in names


# --- stamping -------------------------------------------------------------------------


def test_block_is_typed_by_its_owner() -> None:
    body = {
        "@odata.type": "#Chassis.v1_23_0.Chassis",
        "Oem": {"Redpool": {"FruPartNumber": "0MG81C"}},
    }
    stamp_redpool_oem_types(body)
    assert body["Oem"]["Redpool"]["@odata.type"] == "#Redpool.v1_0_0.RedpoolChassis"


def test_legacy_power_supply_member_is_typed_from_its_parent() -> None:
    body = {"PowerSupplies": [{"Oem": {"Redpool": {"FruPartNumber": "X"}}}]}
    stamp_redpool_oem_types(body)
    assert (
        body["PowerSupplies"][0]["Oem"]["Redpool"]["@odata.type"]
        == "#Redpool.v1_0_0.RedpoolPowerSupply"
    )


def test_untyped_block_outside_power_supplies_is_left_untyped() -> None:
    body = {"Oem": {"Redpool": {"FruPartNumber": "X"}}}
    stamp_redpool_oem_types(body)
    assert "@odata.type" not in body["Oem"]["Redpool"]


def test_documents_without_redpool_are_unchanged() -> None:
    body = {"@odata.type": "#Chassis.v1_23_0.Chassis", "Oem": {"Dell": {"A": 1}}}
    before = json.dumps(body, sort_keys=True)
    stamp_redpool_oem_types(body)
    assert json.dumps(body, sort_keys=True) == before


# --- validation -----------------------------------------------------------------------


def test_valid_block_has_no_issues() -> None:
    doc = {
        "Oem": {
            "Redpool": {
                "@odata.type": "#Redpool.v1_0_0.RedpoolChassis",
                "FruPartNumber": "X",
            }
        }
    }
    assert validate_redpool_oem(doc) == ()


def test_wrong_type_is_reported_with_its_path() -> None:
    doc = {
        "Oem": {
            "Redpool": {
                "@odata.type": "#Redpool.v1_0_0.RedpoolChassis",
                "FruPartNumber": 5,
            }
        }
    }
    issues = validate_redpool_oem(doc)
    assert any(issue.path == "$.Oem.Redpool.FruPartNumber" for issue in issues)


def test_unknown_key_is_rejected() -> None:
    doc = {
        "Oem": {
            "Redpool": {"@odata.type": "#Redpool.v1_0_0.RedpoolChassis", "Invented": 1}
        }
    }
    assert validate_redpool_oem(doc)


def test_missing_type_is_rejected() -> None:
    doc = {"Oem": {"Redpool": {"FruPartNumber": "X"}}}
    assert any("missing" in issue.message for issue in validate_redpool_oem(doc))


def test_unknown_definition_is_rejected() -> None:
    doc = {"Oem": {"Redpool": {"@odata.type": "#Redpool.v1_0_0.RedpoolNonsense"}}}
    assert any("no definition" in issue.message for issue in validate_redpool_oem(doc))


def test_lowercase_block_name_is_not_read_as_redpool() -> None:
    doc = {"Oem": {"redpool": {"Invented": 1}}}
    assert validate_redpool_oem(doc) == ()


# --- fixtures -------------------------------------------------------------------------


@pytest.mark.requires_fixtures
def test_every_fixture_block_validates() -> None:
    blocks = 0
    for path in iter_normalized_documents(FIXTURES):
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        issues = validate_redpool_oem(document)
        assert not issues, f"{path}: {issues[:3]}"
        blocks += sum(1 for _ in _walk_blocks(document))
    assert blocks > 0


def _walk_blocks(node):
    if isinstance(node, dict):
        oem = node.get("Oem")
        if isinstance(oem, dict) and isinstance(oem.get("Redpool"), dict):
            yield oem["Redpool"]
        for value in node.values():
            yield from _walk_blocks(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_blocks(item)


@pytest.mark.requires_fixtures
def test_generator_reproduces_the_committed_schema() -> None:
    spec = importlib.util.spec_from_file_location("gen_redpool_oem", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.build() == _schema()


# --- casing guard ---------------------------------------------------------------------

_FORBIDDEN_KEYS = {"redpool", "Raw"}


def test_normalizers_never_write_lowercase_redpool_or_raw() -> None:
    violations = []
    for path in sorted(NORMALIZERS.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                keys = node.keys
            elif isinstance(node, ast.Subscript) and isinstance(
                node.slice, ast.Constant
            ):
                keys = [node.slice]
            else:
                continue
            for key in keys:
                if isinstance(key, ast.Constant) and key.value in _FORBIDDEN_KEYS:
                    violations.append(
                        f"{path.relative_to(NORMALIZERS)}:{key.lineno}: {key.value!r}"
                    )
    assert not violations, "Use Oem.Redpool with named values; found:\n" + "\n".join(
        violations
    )
