# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Shared pytest hooks for the redpool test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES_PROBE = (
    _REPO_ROOT
    / "fixtures"
    / "Dell"
    / "PowerEdge_R740"
    / "original"
    / "redfish"
    / "v1"
    / "UpdateService"
    / "FirmwareInventory"
)


def fixtures_available() -> bool:
    """True when the fixtures submodule is checked out."""
    return _FIXTURES_PROBE.is_dir()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_fixtures: integration test using the fixtures submodule",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if fixtures_available():
        return
    skip = pytest.mark.skip(
        reason="fixtures submodule not present (see fixtures/README.md)"
    )
    for item in items:
        if item.get_closest_marker("requires_fixtures"):
            item.add_marker(skip)
