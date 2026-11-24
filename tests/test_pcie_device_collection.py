# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Chassis PCIeDevice collections omit members that have no link."""

from __future__ import annotations

import logging

from normalizers.chassis.pcie_devices.base import COLLECTION_MAPPING
from normalizers.evaluator import evaluate
from normalizers.types import NormalizationContext


def test_blank_pcie_device_members_are_omitted() -> None:
    ctx = NormalizationContext(
        data={
            "@odata.id": "/redfish/v1/Chassis/1/PCIeDevices",
            "Members@odata.count": 3,
            "Members": [
                {"@odata.id": "", "Id": "176"},
                {
                    "@odata.id": "/redfish/v1/Chassis/1/PCIeDevices/3",
                },
                {"Id": "178"},
            ],
        },
        client=None,
        logger=logging.getLogger("test"),
        vendor="HPE",
    )
    out = evaluate(COLLECTION_MAPPING, ctx)
    assert out["Members"] == [
        {"@odata.id": "/redfish/v1/Chassis/1/PCIeDevices/3"},
    ]
    assert out["Members@odata.count"] == 1
