# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

import sys

from scripts import generate_normalized_outputs, validate_redfish_schema


def test_fixture_scripts_select_the_same_model(tmp_path, monkeypatch, capsys):
    fixtures = tmp_path / "captures"
    selected = fixtures / "Dell" / "PowerEdge_R740"
    normalized = selected / "normalized"
    normalized.mkdir(parents=True)
    document = normalized / "index.json"
    document.write_text("{}")
    for vendor, model in (("Dell", "PowerEdge_R640"), ("Other", "PowerEdge_R740")):
        other = fixtures / vendor / model / "normalized"
        other.mkdir(parents=True)
        (other / "index.json").write_text("{}")

    monkeypatch.setenv("REDPOOL_FIXTURES", str(tmp_path / "unused"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "script",
            "--fixtures",
            str(fixtures),
            "--vendor",
            "dell",
            "--model",
            "poweredge_r740",
        ],
    )
    generated = []
    monkeypatch.setattr(
        generate_normalized_outputs,
        "generate_for_model",
        lambda proxy, vendor, model_dir, limit: generated.append((vendor, model_dir)),
    )
    generate_normalized_outputs.main()
    assert generated == [("Dell", str(selected))]

    monkeypatch.setattr(
        validate_redfish_schema, "schema_bundle_available", lambda: True
    )
    assert validate_redfish_schema.main() == 0
    assert "checked=1 valid=0 invalid=0 skipped=1" in capsys.readouterr().out


def test_filtered_validation_requires_normalized_documents(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "Dell" / "PowerEdge_R740" / "original").mkdir(parents=True)
    monkeypatch.setattr(
        sys,
        "argv",
        ["script", "--fixtures", str(tmp_path), "--model", "PowerEdge_R740"],
    )
    monkeypatch.setattr(
        validate_redfish_schema, "schema_bundle_available", lambda: True
    )

    assert validate_redfish_schema.main() == 2
    assert "run generate_normalized_outputs.py first" in capsys.readouterr().err
