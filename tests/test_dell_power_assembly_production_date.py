# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell Power Assembly ``ProductionDate`` parsing. Fixture dates are in normalized JSON."""

from __future__ import annotations

from normalizers.chassis.power.dell import parse_dell_assembly_production_date


def test_parse_production_date_iso_z():
    assert parse_dell_assembly_production_date("2023-01-31T23:59:00Z") == (
        5,
        2023,
        "2023-01-31",
    )


def test_parse_empty_returns_none():
    assert parse_dell_assembly_production_date("") is None
    assert parse_dell_assembly_production_date("not-a-date") is None
