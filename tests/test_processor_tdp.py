# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Processor TDP is passed through only when the BMC reports it."""

import logging

from normalizers.evaluator import evaluate
from normalizers.systems.processors.base import BaseProcessorNormalizer
from normalizers.systems.processors.supermicro import SupermicroProcessorNormalizer
from normalizers.types import NormalizationContext

PATH = "/redfish/v1/Systems/1/Processors/1"


def _evaluate(normalizer, data):
    body = {"@odata.id": PATH, "@odata.type": "#Processor.v1_20_0.Processor", "Id": "1"}
    body.update(data)
    ctx = NormalizationContext(data=body, client=None, logger=logging.getLogger("t"))
    return evaluate(normalizer.field_map(), ctx)


def test_missing_tdp_is_omitted_not_zero():
    assert "TDPWatts" not in _evaluate(BaseProcessorNormalizer(), {})


def test_reported_tdp_passes_through():
    assert _evaluate(BaseProcessorNormalizer(), {"TDPWatts": 250})["TDPWatts"] == 250


def test_supermicro_keeps_max_tdp_and_uses_it_for_tdp_when_none_is_sent():
    out = _evaluate(SupermicroProcessorNormalizer(), {"MaxTDPWatts": 150})
    assert out["MaxTDPWatts"] == 150
    assert out["TDPWatts"] == 150


def test_supermicro_null_max_tdp_is_omitted():
    assert "MaxTDPWatts" not in _evaluate(
        SupermicroProcessorNormalizer(), {"MaxTDPWatts": None}
    )
