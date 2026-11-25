# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE PCIe slot normalization."""

from .base import BasePCIeSlotsNormalizer


def _hpe_slots(ctx):
    slots = ctx.data.get("Slots", [])
    if not isinstance(slots, list):
        return slots
    return [
        {**slot, "SlotType": "OCP3Small"}
        if isinstance(slot, dict) and slot.get("SlotType") == "OCPSmall"
        else slot
        for slot in slots
    ]


class HPEPCIeSlotsNormalizer(BasePCIeSlotsNormalizer):
    def field_map(self):
        fields = super().field_map()
        fields["Slots"] = _hpe_slots
        return fields
