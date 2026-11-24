# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Directory roots for vendored collector/exporter Git submodules."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
THIRD_PARTY = REPO_ROOT / "third_party"
REDFISH_INVENTORY_EXPORTER_ROOT = THIRD_PARTY / "redfish-inventory-exporter"
FISHYMETRICS_ROOT = THIRD_PARTY / "fishymetrics"
