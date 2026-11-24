# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Vendor-neutral checks for whether a Status needs a PCIe or other fallback.

Used by the Dell, HPE and Lenovo normalizers alike.
"""

from __future__ import annotations

from typing import Any


def _status_field_unknown_or_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        s = value.strip()
        return not s or s.casefold() == "unknown"
    return False


def status_field_unknown_or_empty(value: Any) -> bool:
    """True if *value* is missing or Redfish-style ``Unknown`` (public alias for merges)."""
    return _status_field_unknown_or_empty(value)


def status_needs_pcie_fill(status: Any) -> bool:
    """True when ``Health`` or ``State`` is missing or ``Unknown`` (PCIe may supply real values)."""
    if not isinstance(status, dict):
        return True
    return _status_field_unknown_or_empty(
        status.get("Health")
    ) or _status_field_unknown_or_empty(status.get("State"))


def adapter_status_needs_pcie_fill(status: Any) -> bool:
    """Like :func:`status_needs_pcie_fill` but also treats unknown ``HealthRollup`` as a gap."""
    if not isinstance(status, dict):
        return True
    return (
        _status_field_unknown_or_empty(status.get("Health"))
        or _status_field_unknown_or_empty(status.get("State"))
        or _status_field_unknown_or_empty(status.get("HealthRollup"))
    )
