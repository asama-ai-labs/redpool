# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell ``DellMemory.ManufactureDate`` parsing. Fixture dates are in normalized JSON."""

from __future__ import annotations

import unittest

from normalizers.systems.memory.dell import parse_dell_oem_manufacture_date


class TestParseDellOemManufactureDate(unittest.TestCase):
    def test_idrac_date(self):
        w, y, iso = parse_dell_oem_manufacture_date("Mon Jul 17 ::1 2023 UTC")
        self.assertEqual((w, y, iso), (29, 2023, "2023-07-17"))

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_dell_oem_manufacture_date(""))
        self.assertIsNone(parse_dell_oem_manufacture_date("not a date"))
        self.assertIsNone(parse_dell_oem_manufacture_date(None))  # type: ignore[arg-type]
