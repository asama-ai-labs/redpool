#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Generate the published Redpool OEM schema from the normalized fixtures.

Every ``Oem.Redpool`` object in ``fixtures/*/*/normalized`` is grouped by the
definition it names (``#Redpool.v1_0_0.Redpool<Owner>``). The property names
and value types observed there become that definition's properties, so the
schema describes what Redpool actually emits. ``HpeSmartStorage`` is shared by
several owners and is defined once.

Usage (from the repository root):

    uv run python scripts/generate_redpool_oem_schema.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent
FIXTURES = PUBLIC / "fixtures"
OUT = PUBLIC / "schemas" / "json-schema" / "Redpool.v1_0_0.json"
NAMESPACE = "#Redpool.v1_0_0."
SCHEMA_ID = (
    "https://github.com/asama-ai-labs/redpool/schemas/json-schema/Redpool.v1_0_0.json"
)
SHARED_NESTED = {"HpeSmartStorage"}
# Fields supported by the schema even when absent from the current captures.
KNOWN_EXTRA = {
    "HpeSmartStorage": {
        "ChargeLevelPercent": {"number"},
        "MaximumCapWatts": {"number"},
        "RemainingChargeTimeSeconds": {"number"},
    },
    "RedpoolBios": {"BypassBIOSPwFlag": {"boolean"}},
    "RedpoolLogEntry": {"TotalSequenceNumber": {"string"}},
    "RedpoolNetworkAdapter": {"Location": {"string"}},
}
DESCRIPTION = "Value normalized into Oem.Redpool. It is not defined by DMTF; see docs/REDPOOL_OEM_SCHEMA.md."


def _json_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _collect(body, owners, nested):
    if isinstance(body, list):
        for item in body:
            _collect(item, owners, nested)
        return
    if not isinstance(body, dict):
        return
    oem = body.get("Oem")
    if isinstance(oem, dict) and isinstance(oem.get("Redpool"), dict):
        rp = oem["Redpool"]
        odata_type = rp.get("@odata.type")
        if isinstance(odata_type, str) and odata_type.startswith(NAMESPACE):
            owner = odata_type[len(NAMESPACE) :]
            owners[owner]  # a block may hold only shared nested values
            for key, value in rp.items():
                if key == "@odata.type":
                    continue
                if key in SHARED_NESTED and isinstance(value, dict):
                    owners[owner][key].add("object")
                    for nkey, nvalue in value.items():
                        nested[key][nkey].add(_json_type(nvalue))
                    nested[key]["Kind"].add("string")
                    continue
                owners[owner][key].add(_json_type(value))
    for value in body.values():
        _collect(value, owners, nested)


def build() -> dict:
    owners = defaultdict(lambda: defaultdict(set))
    nested = defaultdict(lambda: defaultdict(set))
    for path in sorted(FIXTURES.glob("*/*/normalized/**/*.json")):
        try:
            _collect(json.loads(path.read_text(encoding="utf-8")), owners, nested)
        except (OSError, ValueError):
            continue

    def prop(types, description=DESCRIPTION):
        types = sorted(types)
        spec = {
            "type": types[0] if len(types) == 1 else types,
            "description": description,
        }
        return spec

    definitions = {}
    for shared, props in nested.items():
        merged = {k: prop(v) for k, v in props.items()}
        for k, v in KNOWN_EXTRA.get(shared, {}).items():
            merged.setdefault(k, prop(v))
        definitions[shared] = {
            "type": "object",
            "description": "Named values Redpool reads from a vendor's SmartStorage payload.",
            "properties": dict(sorted(merged.items())),
            "additionalProperties": False,
        }

    for owner, fields in KNOWN_EXTRA.items():
        if owner not in SHARED_NESTED:
            for key, types in fields.items():
                owners[owner][key].update(types)

    for owner, props in owners.items():
        resource = owner.removeprefix("Redpool")
        definitions[owner] = {
            "type": "object",
            "description": f"Redpool-normalized vendor data on a {resource} resource.",
            "properties": {
                "@odata.type": {"type": "string", "const": f"{NAMESPACE}{owner}"},
                **{
                    key: (
                        {"$ref": f"#/definitions/{key}"}
                        if key in SHARED_NESTED
                        else prop(types)
                    )
                    for key, types in sorted(props.items())
                },
            },
            "additionalProperties": False,
        }

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": SCHEMA_ID,
        "title": "Redpool OEM extension, version 1.0.0",
        "description": "The Oem.Redpool block that Redpool adds to normalized Redfish resources.",
        "definitions": dict(sorted(definitions.items())),
    }


def main() -> int:
    schema = build()
    OUT.write_text(
        json.dumps(schema, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT} with {len(schema['definitions'])} definitions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
