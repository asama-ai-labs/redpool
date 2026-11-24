# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""TotalEnabledCores is what the BMC reports; TotalCores does not imply it."""

import logging
import unittest

from normalizers.evaluator import evaluate
from normalizers.systems.processors.base import BaseProcessorNormalizer
from normalizers.types import NormalizationContext


def _enabled_cores(data):
    ctx = NormalizationContext(
        data=data,
        client=None,
        logger=logging.getLogger("t"),
        vendor="Dell",
        resource_path="/redfish/v1/Systems/1/Processors/CPU1",
    )
    return evaluate(BaseProcessorNormalizer().field_map(), ctx)["TotalEnabledCores"]


class TotalEnabledCoresTests(unittest.TestCase):
    def test_reported_value_is_kept(self) -> None:
        self.assertEqual(
            _enabled_cores({"TotalCores": 16, "TotalEnabledCores": 12}), 12
        )

    def test_total_cores_is_not_copied(self) -> None:
        self.assertIsNone(_enabled_cores({"TotalCores": 16}))


if __name__ == "__main__":
    unittest.main()
