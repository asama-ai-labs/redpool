# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE ``DIMMManufacturingDate`` (``YYWW``) parsing. Fixture dates are in normalized JSON."""

from __future__ import annotations

import unittest
from datetime import date

from normalizers.systems.memory.hpe import parse_hpe_dimmm_manufacturing_date


class TestParseHpeDimmmManufacturingDate(unittest.TestCase):
    def test_yyww(self):
        w, y, iso = parse_hpe_dimmm_manufacturing_date("2409")
        self.assertEqual(w, 9)
        self.assertEqual(y, 2024)
        self.assertEqual(iso, date.fromisocalendar(2024, 9, 1).isoformat())

    def test_invalid(self):
        self.assertIsNone(parse_hpe_dimmm_manufacturing_date(""))
        self.assertIsNone(parse_hpe_dimmm_manufacturing_date("240"))
        self.assertIsNone(parse_hpe_dimmm_manufacturing_date("abcd"))
        self.assertIsNone(parse_hpe_dimmm_manufacturing_date("2454"))
