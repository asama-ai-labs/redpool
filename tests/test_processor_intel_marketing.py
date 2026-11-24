# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Intel M50 / Rack Scale puts the CPU marketing line in ProcessorId.VendorId.

Reading it lives in the Intel processor module. The shared base does not look at it.
"""

from __future__ import annotations

import logging

from normalizers.systems.processors.base import BaseProcessorNormalizer
from normalizers.systems.processors.intel import IntelProcessorNormalizer
from normalizers.types import NormalizationContext

_MARKETING = "Intel(R) Xeon(R) Gold 6338 CPU @ 2.00GHz"


def _ctx(data: dict) -> NormalizationContext:
    return NormalizationContext(
        data=data,
        client=None,
        logger=logging.getLogger("test"),
        prefetched={},
        vendor="",
    )


def _data() -> dict:
    return {
        "Model": "Intel Xeon processor",
        "ProcessorId": {"VendorId": _MARKETING},
        "Manufacturer": "Intel Corporation",
    }


def test_intel_reads_model_part_number_and_base_speed_from_vendor_id() -> None:
    m = IntelProcessorNormalizer().field_map()
    ctx = _ctx(_data())
    assert m["Model"](ctx) == "Intel(R) Xeon(R) Gold 6338"
    assert m["PartNumber"](ctx) == "Xeon Gold 6338"
    assert m["BaseSpeedMHz"](ctx) == 2000


def test_intel_keeps_a_complete_model() -> None:
    data = _data()
    data["Model"] = "Intel(R) Xeon(R) Gold 5317 CPU @ 3.00GHz"
    m = IntelProcessorNormalizer().field_map()
    assert m["Model"](_ctx(data)) == "Intel(R) Xeon(R) Gold 5317"


def test_base_ignores_the_vendor_id_marketing_line() -> None:
    m = BaseProcessorNormalizer().field_map()
    ctx = _ctx(_data())
    assert m["Model"](ctx) == "Intel Xeon processor"
    assert m["BaseSpeedMHz"](ctx) is None
