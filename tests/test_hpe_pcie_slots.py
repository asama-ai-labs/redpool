# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

import logging

from normalizers.apply import normalize_resource
from normalizers.registry import get_resource_entry
from normalizers.types import NormalizationContext


def test_hpe_pcie_slot_type_matches_pinned_schema():
    slots = [{"SlotType": "OCPSmall"}, {"SlotType": "FullLength"}, {}]
    entry = get_resource_entry("Chassis/PCIeSlots")
    result = normalize_resource(
        entry.for_vendor("HPE"),
        NormalizationContext(
            data={"Slots": slots},
            client=None,
            logger=logging.getLogger(__name__),
            vendor="HPE",
        ),
    )
    assert result["Slots"] == [
        {"SlotType": "OCP3Small"},
        {"SlotType": "FullLength"},
        {},
    ]
    assert slots[0]["SlotType"] == "OCPSmall"
