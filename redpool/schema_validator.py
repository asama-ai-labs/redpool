# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Validate a Redfish JSON document against the pinned DMTF JSON Schema bundle.

Schemas live in the ``Redfish-Publications`` submodule
(``third_party/Redfish-Publications/json-schema``). ``$ref`` URIs of the form
``http://redfish.dmtf.org/schemas/v1/<file>.json`` are read from that directory.
``@odata.type`` selects the versioned file: ``#Processor.v1_20_0.Processor``
loads ``Processor.v1_20_0.json#/definitions/Processor``.

Documents whose ``@odata.type`` has no file in the bundle (OEM types) are
skipped. Swordfish ``$ref`` URIs (``.../schemas/swordfish/v1/<file>.json``) are read
from the ``Swordfish-Publications`` submodule
(``third_party/Swordfish-Publications/json-schema``). A ``$ref`` to any other
location cannot be resolved and is reported as an issue. The schemas are draft-07
plus Redfish annotation keywords, which this checker ignores.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urldefrag

import jsonschema
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT7

_SCHEMA_URI_PREFIX = "http://redfish.dmtf.org/schemas/v1/"
_SWORDFISH_URI_PREFIX = "http://redfish.dmtf.org/schemas/swordfish/v1/"
_MAX_ISSUES = 15

_resources: dict[str, Resource[Any]] = {}
_validators: dict[str, jsonschema.Draft7Validator] = {}
_registry: Registry[Any] | None = None


def schema_dir() -> Path:
    """Directory of ``*.json`` schema files in the Redfish-Publications submodule."""
    return (
        Path(__file__).resolve().parent.parent
        / "third_party"
        / "Redfish-Publications"
        / "json-schema"
    )


def swordfish_schema_dir() -> Path:
    """Directory of ``*.json`` schema files in the Swordfish-Publications submodule."""
    return (
        Path(__file__).resolve().parent.parent
        / "third_party"
        / "Swordfish-Publications"
        / "json-schema"
    )


def schema_bundle_available() -> bool:
    return (schema_dir() / "redfish-schema-v1.json").is_file() and (
        swordfish_schema_dir() / "Volume.json"
    ).is_file()


@dataclass(frozen=True)
class SchemaIssue:
    path: str
    message: str


@dataclass(frozen=True)
class SchemaResult:
    """Outcome for one JSON document.

    ``status`` is ``valid``, ``invalid``, or ``skipped``. Skipped documents have
    no standard ``@odata.type`` in the pinned bundle. ``detail`` explains a skip.
    """

    status: str
    odata_type: str | None
    detail: str
    issues: tuple[SchemaIssue, ...]


def _split_odata_type(odata_type: str) -> tuple[str, str] | None:
    """Return ``(Namespace, TypeName)`` for ``#Namespace.TypeName``."""
    if not odata_type.startswith("#") or "." not in odata_type:
        return None
    namespace, _, name = odata_type[1:].rpartition(".")
    if not namespace or not name:
        return None
    if "/" in namespace or "\\" in namespace or ".." in namespace.split("."):
        return None
    return namespace, name


def is_dmtf_type_newer_than_bundle(odata_type: str | None) -> bool:
    """True when ``odata_type`` names a DMTF resource whose version is not in the bundle.

    Every DMTF resource has an unversioned ``<Name>.json`` next to its versioned files.
    A versioned namespace with no file, but with that unversioned file, is a DMTF type
    at a version newer than the pinned bundle. OEM types have neither file.
    """
    if not isinstance(odata_type, str):
        return False
    parsed = _split_odata_type(odata_type)
    if parsed is None:
        return False
    namespace, _name = parsed
    base, dot, version = namespace.partition(".")
    if not dot or not version.startswith("v"):
        return False
    if (schema_dir() / f"{namespace}.json").is_file():
        return False
    return (schema_dir() / f"{base}.json").is_file()


def deprecation_notes(document: Any) -> list[str]:
    """Deprecated schemas and properties a document uses, from the pinned bundle.

    Returns ``type:<odata.type>`` when the resource schema is deprecated, and
    ``property:<Type>.<Name>`` for each present property whose definition is deprecated.
    This is information for the operator; it never fails validation.
    """
    if not isinstance(document, dict):
        return []
    raw_type = document.get("@odata.type")
    parsed = _split_odata_type(raw_type) if isinstance(raw_type, str) else None
    if parsed is None:
        return []
    namespace, name = parsed
    path = schema_dir() / f"{namespace}.json"
    if not path.is_file():
        return []
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    definition = schema.get("definitions", {}).get(name, {})
    notes: list[str] = []
    if definition.get("deprecated"):
        notes.append(f"type:{raw_type}")
    for prop, spec in definition.get("properties", {}).items():
        if prop in document and isinstance(spec, dict) and spec.get("deprecated"):
            notes.append(f"property:{namespace.split('.')[0]}.{prop}")
    return notes


def _retrieve(uri: str) -> Resource[Any]:
    cached = _resources.get(uri)
    if cached is not None:
        return cached
    bare, _fragment = urldefrag(uri)
    if bare.startswith(_SCHEMA_URI_PREFIX):
        directory, prefix = schema_dir(), _SCHEMA_URI_PREFIX
    elif bare.startswith(_SWORDFISH_URI_PREFIX):
        directory, prefix = swordfish_schema_dir(), _SWORDFISH_URI_PREFIX
    else:
        raise Unresolvable(ref=uri)
    filename = unquote(bare[len(prefix) :])
    if not filename or "/" in filename or filename.startswith("."):
        raise Unresolvable(ref=uri)
    path = directory / filename
    if not path.is_file():
        raise Unresolvable(ref=uri)
    contents = json.loads(path.read_text(encoding="utf-8"))
    loaded: Resource[Any] = Resource(contents=contents, specification=DRAFT7)  # type: ignore[call-arg]
    _resources[uri] = loaded
    _resources[bare] = loaded
    return loaded


def _registry_for_bundle() -> Registry[Any]:
    global _registry
    if _registry is None:
        _registry = Registry(retrieve=_retrieve)  # type: ignore[call-arg]
    return _registry


def _validator_for(namespace: str, name: str) -> jsonschema.Draft7Validator:
    ref = f"{_SCHEMA_URI_PREFIX}{namespace}.json#/definitions/{name}"
    cached = _validators.get(ref)
    if cached is not None:
        return cached
    validator = jsonschema.Draft7Validator(
        {"$ref": ref},
        registry=_registry_for_bundle(),
        format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER,
    )
    _validators[ref] = validator
    return validator


def _subschema_is_weak(subschema: Any) -> bool:
    """True for the idRef and null branches of a Redfish ``anyOf``.

    Collection and resource schemas are ``anyOf: [idRef, <resource>]``. A full
    document fails the idRef branch with "additional properties are not
    allowed", which hides the real failure on the resource branch. The null
    alternative next to a typed schema does the same for a bad value.
    """
    if not isinstance(subschema, dict):
        return False
    ref = subschema.get("$ref")
    if isinstance(ref, str) and ref.endswith("#/definitions/idRef"):
        return True
    return subschema.get("type") == "null" and set(subschema) == {"type"}


def _error_depth(error: jsonschema.ValidationError) -> int:
    if not error.context:
        return len(error.absolute_path)
    return max(_error_depth(child) for child in error.context)


def _leaves(error: jsonschema.ValidationError) -> list[jsonschema.ValidationError]:
    if error.validator not in {"anyOf", "oneOf"} or not error.context:
        if not error.context:
            return [error]
        leaves: list[jsonschema.ValidationError] = []
        for child in error.context:
            leaves.extend(_leaves(child))
        return leaves or [error]

    subschemas = (
        error.schema.get(error.validator) if isinstance(error.schema, dict) else None
    )
    groups: dict[int, list[jsonschema.ValidationError]] = {}
    for child in error.context:
        index = child.schema_path[0] if child.schema_path else None
        if isinstance(index, int):
            groups.setdefault(index, []).append(child)
    if not groups:
        leaves = []
        for child in error.context:
            leaves.extend(_leaves(child))
        return leaves or [error]
    indexes = list(groups)
    if isinstance(subschemas, list):
        strong = [
            index
            for index in indexes
            if index < len(subschemas) and not _subschema_is_weak(subschemas[index])
        ]
        if strong:
            indexes = strong
    if len(indexes) > 1:
        indexes = [
            max(
                indexes,
                key=lambda index: max(_error_depth(child) for child in groups[index]),
            )
        ]
    leaves = []
    for index in indexes:
        for child in groups[index]:
            leaves.extend(_leaves(child))
    return leaves or [error]


def _issues_from(error: jsonschema.ValidationError) -> list[SchemaIssue]:
    issues = []
    for leaf in _leaves(error):
        path = getattr(leaf, "json_path", None) or "$"
        issues.append(SchemaIssue(path=path, message=leaf.message))
    return issues


def validate_document(document: Any) -> SchemaResult:
    """Validate one Redfish JSON value. Non-objects and unknown types are skipped."""
    if not isinstance(document, dict):
        return SchemaResult("skipped", None, "not a JSON object", ())
    raw_type = document.get("@odata.type")
    if not isinstance(raw_type, str) or not raw_type:
        return SchemaResult("skipped", None, "no @odata.type", ())
    parsed = _split_odata_type(raw_type)
    if parsed is None:
        return SchemaResult("skipped", raw_type, "unrecognized @odata.type", ())
    namespace, name = parsed
    schema_path = schema_dir() / f"{namespace}.json"
    if not schema_path.is_file():
        return SchemaResult("skipped", raw_type, "no DMTF schema for this type", ())
    if not schema_bundle_available():
        raise FileNotFoundError(
            f"Redfish JSON Schema bundle is not checked out at {schema_dir()}"
        )
    validator = _validator_for(namespace, name)
    issues: list[SchemaIssue] = []
    try:
        for error in validator.iter_errors(document):
            issues.extend(_issues_from(error))
            if len(issues) >= _MAX_ISSUES:
                break
    except Unresolvable as exc:
        issues.append(SchemaIssue("$", f"unresolvable schema: {exc}"))
    issues = issues[:_MAX_ISSUES]
    if issues:
        return SchemaResult("invalid", raw_type, "", tuple(issues))
    return SchemaResult("valid", raw_type, "", ())


def iter_normalized_documents(
    fixtures: Path,
    *,
    vendor: str | None = None,
    model: str | None = None,
) -> Iterator[Path]:
    """Yield ``fixtures/<Vendor>/<Model>/normalized/**/*.json`` paths."""
    if vendor:
        vendor_dirs = [fixtures / vendor]
    else:
        vendor_dirs = sorted(p for p in fixtures.iterdir() if p.is_dir())
    for vendor_dir in vendor_dirs:
        if not vendor_dir.is_dir():
            continue
        if model:
            model_dirs = [vendor_dir / model]
        else:
            model_dirs = sorted(p for p in vendor_dir.iterdir() if p.is_dir())
        for model_dir in model_dirs:
            normalized = model_dir / "normalized"
            if not normalized.is_dir():
                continue
            yield from sorted(normalized.rglob("*.json"))


def validate_file(path: Path) -> SchemaResult:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return SchemaResult(
            "invalid", None, "", (SchemaIssue("$", f"invalid JSON: {exc}"),)
        )
    return validate_document(document)


# The published Redpool OEM schema (Redpool.v1_0_0) lives beside the code.
_REDPOOL_OEM_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent
    / "schemas"
    / "json-schema"
    / "Redpool.v1_0_0.json"
)
_REDPOOL_OEM_NAMESPACE = "#Redpool.v1_0_0."


@lru_cache(maxsize=1)
def _redpool_oem_definitions() -> dict[str, Any]:
    return json.loads(_REDPOOL_OEM_SCHEMA_PATH.read_text(encoding="utf-8"))[
        "definitions"
    ]


def redpool_oem_schema_available() -> bool:
    return _REDPOOL_OEM_SCHEMA_PATH.is_file()


def _redpool_oem_blocks(
    node: Any, path: str = "$"
) -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        oem = node.get("Oem")
        if isinstance(oem, dict) and isinstance(oem.get("Redpool"), dict):
            yield f"{path}.Oem.Redpool", oem["Redpool"]
        for key, value in node.items():
            if key != "Oem":
                yield from _redpool_oem_blocks(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _redpool_oem_blocks(item, f"{path}[{index}]")


def validate_redpool_oem(document: Any) -> tuple[SchemaIssue, ...]:
    """Validate every ``Oem.Redpool`` block in *document* against Redpool.v1_0_0.

    A block with no ``@odata.type`` in the namespace, or naming a definition the
    schema does not have, is an issue. The block itself is checked against that
    definition's properties and types.
    """
    definitions = _redpool_oem_definitions()
    issues: list[SchemaIssue] = []
    for path, block in _redpool_oem_blocks(document):
        odata_type = block.get("@odata.type")
        if not isinstance(odata_type, str) or not odata_type.startswith(
            _REDPOOL_OEM_NAMESPACE
        ):
            issues.append(SchemaIssue(path, "missing or foreign @odata.type"))
            continue
        name = odata_type[len(_REDPOOL_OEM_NAMESPACE) :]
        if name not in definitions:
            issues.append(SchemaIssue(path, f"no definition {name} in Redpool.v1_0_0"))
            continue
        validator = jsonschema.Draft7Validator(
            {"$ref": f"#/definitions/{name}", "definitions": definitions}
        )
        for error in sorted(validator.iter_errors(block), key=str):
            where = "".join(
                f".{part}" if isinstance(part, str) else f"[{part}]"
                for part in error.absolute_path
            )
            issues.append(SchemaIssue(f"{path}{where}", error.message))
    return tuple(issues)
