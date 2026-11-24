# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""NetworkAdapter SKU is passed through when the BMC sends it."""

import logging

from normalizers.chassis.network_adapters.base import BaseNetworkAdapterNormalizer
from normalizers.evaluator import evaluate
from normalizers.types import NormalizationContext


def _evaluate(data):
    body = {
        "@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters/slot-1",
        "@odata.type": "#NetworkAdapter.v1_9_0.NetworkAdapter",
        "Id": "slot-1",
    }
    body.update(data)
    ctx = NormalizationContext(data=body, client=None, logger=logging.getLogger("t"))
    return evaluate(BaseNetworkAdapterNormalizer().field_map(), ctx)


def test_sku_passes_through():
    assert _evaluate({"SKU": "7ZT7A00000"})["SKU"] == "7ZT7A00000"


def test_missing_sku_is_omitted():
    assert "SKU" not in _evaluate({})
