# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Fixture layout: the DMTF mockup format.

The resource at ``/redfish/v1/<path>`` is stored as
``<root>/redfish/v1/<path>/index.json``, as written by DMTF
Redfish-Mockup-Creator and served by Redfish-Mockup-Server.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Iterator

INDEX = "index.json"


def uri_to_relpath(uri: str) -> Path:
    """``/redfish/v1/Systems/1`` (or ``Systems/1``) -> ``redfish/v1/Systems/1/index.json``."""
    rel = uri.split("?", 1)[0].strip("/")
    if rel != "redfish/v1" and not rel.startswith("redfish/v1/"):
        rel = f"redfish/v1/{rel}".rstrip("/")
    return Path(*PurePosixPath(rel).parts) / INDEX


def relpath_to_uri(rel: Path) -> str:
    """``redfish/v1/Systems/1/index.json`` -> ``/redfish/v1/Systems/1``."""
    return "/" + Path(rel).parent.as_posix()


def iter_mockup_files(root: Path):
    """Yield every ``index.json`` under a mockup root, sorted."""
    yield from sorted(Path(root).rglob(INDEX))


def iter_fixture_models(
    fixtures: Path, *, vendor: str | None = None, model: str | None = None
) -> Iterator[Path]:
    """Yield model directories with optional case-insensitive name filters."""
    for path in sorted(fixtures.glob("*/*")):
        if not path.is_dir() or path.parent.name.startswith("."):
            continue
        if vendor and path.parent.name.lower() != vendor.lower():
            continue
        if model and path.name.lower() != model.lower():
            continue
        yield path
