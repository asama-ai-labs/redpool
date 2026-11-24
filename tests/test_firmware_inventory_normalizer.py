# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""RelatedItem URI labels. Fixture firmware documents are in normalized JSON."""

from __future__ import annotations

import pytest

from normalizers.firmware_inventory._shared.firmware_inventory import (
    parse_related_item_uri,
)


@pytest.mark.parametrize(
    ("uri", "kind", "ref", "scope", "location"),
    [
        (
            "/redfish/v1/Systems/1/Storage/M.2/Drives/Drive.M.2_Bay_0",
            "drive",
            "Drive.M.2_Bay_0",
            "M.2",
            "M.2 - Drive0",
        ),
        (
            "/redfish/v1/Chassis/1/PCIeDevices/slot_3",
            "pcie",
            "slot_3",
            "",
            "PCIe slot_3",
        ),
        ("/redfish/v1/Managers/1", "manager", "1", "", "BMC"),
        ("/redfish/v1/Systems/1/Bios", "bios", "Bios", "", "BIOS"),
        ("/redfish/v1/Systems/1/Processors/GPU4", "processor", "GPU4", "", "GPU4"),
    ],
)
def test_parse_related_item_uri(uri, kind, ref, scope, location):
    parsed = parse_related_item_uri(uri)
    assert parsed["related_kind"] == kind
    assert parsed["related_ref"] == ref
    assert parsed["related_scope"] == scope
    assert parsed["related_location"] == location
