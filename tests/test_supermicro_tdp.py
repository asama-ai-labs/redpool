# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Supermicro: TDPWatts falls back to MaxTDPWatts only when the BMC sends no TDPWatts."""

from __future__ import annotations

import logging
import unittest

from normalizers.evaluator import evaluate
from normalizers.systems.processors.supermicro import SupermicroProcessorNormalizer
from normalizers.types import NormalizationContext


def _normalize(data: dict) -> dict:
    ctx = NormalizationContext(
        data=data,
        client=None,
        logger=logging.getLogger("test"),
        prefetched={},
        vendor="Supermicro",
    )
    return evaluate(SupermicroProcessorNormalizer().field_map(), ctx)


class SupermicroTdpFallbackTests(unittest.TestCase):
    def test_max_tdp_is_used_when_tdp_is_absent(self) -> None:
        out = _normalize({"Id": "1", "MaxTDPWatts": 150})
        self.assertEqual(out["TDPWatts"], 150)
        self.assertEqual(out["MaxTDPWatts"], 150)

    def test_sent_tdp_wins_over_max_tdp(self) -> None:
        out = _normalize({"Id": "1", "TDPWatts": 120, "MaxTDPWatts": 150})
        self.assertEqual(out["TDPWatts"], 120)

    def test_no_tdp_value_is_omitted(self) -> None:
        self.assertNotIn("TDPWatts", _normalize({"Id": "1"}))


if __name__ == "__main__":
    unittest.main()
