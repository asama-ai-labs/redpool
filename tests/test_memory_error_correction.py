# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""ErrorCorrection is what the BMC reported; a wider bus than data path is not a scheme."""

import logging
import re
import unittest

from normalizers._shared.memory_ecc import memory_ecc_mode_enabled
from normalizers.systems.memory.base import BaseMemoryNormalizer
from normalizers.systems.memory.lenovo_memory import LenovoMemoryNormalizer
from normalizers.systems.processors.base import BaseProcessorNormalizer
from normalizers.types import NormalizationContext

LOGGER = logging.getLogger("test")
MEM = "/redfish/v1/Systems/1/Memory"
CPU = "/redfish/v1/Systems/1/Processors/CPU1"


def _ctx(data, client=None):
    ctx = NormalizationContext(data=data, client=client, logger=LOGGER)
    return ctx


class TestReportedOnly(unittest.TestCase):
    def test_wider_bus_without_a_reported_scheme_is_null(self) -> None:
        dimm = {"DataWidthBits": 64, "BusWidthBits": 72, "CapacityMiB": 65536}
        for normalizer in (BaseMemoryNormalizer(), LenovoMemoryNormalizer()):
            with self.subTest(normalizer=type(normalizer).__name__):
                got = normalizer.field_map()["ErrorCorrection"](_ctx(dimm))
                self.assertIsNone(got)

    def test_lenovo_ecc_bits_do_not_imply_a_scheme(self) -> None:
        dimm = {
            "DataWidthBits": 64,
            "BusWidthBits": 72,
            "Oem": {"Lenovo": {"EccBits": 8}},
        }
        got = LenovoMemoryNormalizer().field_map()["ErrorCorrection"](_ctx(dimm))
        self.assertIsNone(got)

    def test_reported_scheme_passes_through(self) -> None:
        for scheme in ("MultiBitECC", "SingleBitECC", "NoECC", "AddressParity"):
            with self.subTest(scheme=scheme):
                dimm = {
                    "ErrorCorrection": scheme,
                    "DataWidthBits": 64,
                    "BusWidthBits": 72,
                }
                for normalizer in (BaseMemoryNormalizer(), LenovoMemoryNormalizer()):
                    got = normalizer.field_map()["ErrorCorrection"](_ctx(dimm))
                    self.assertEqual(got, scheme)


class TestEccModeEnabled(unittest.TestCase):
    def test_every_dimm_reports_ecc(self) -> None:
        self.assertIs(memory_ecc_mode_enabled(["MultiBitECC", "SingleBitECC"]), True)

    def test_a_dimm_without_a_scheme_makes_it_unknown(self) -> None:
        for values in ([None], [""], ["MultiBitECC", None], [None, "MultiBitECC"]):
            with self.subTest(values=values):
                self.assertIsNone(memory_ecc_mode_enabled(values))

    def test_a_non_ecc_dimm_makes_it_false_even_with_unknowns(self) -> None:
        self.assertIs(memory_ecc_mode_enabled(["NoECC"]), False)
        self.assertIs(memory_ecc_mode_enabled([None, "NoECC"]), False)
        self.assertIs(memory_ecc_mode_enabled(["AddressParity"]), False)

    def test_no_dimms_is_true_as_before(self) -> None:
        self.assertIs(memory_ecc_mode_enabled([]), True)


class _Rest:
    def __init__(self, body):
        self.status = 200
        self.dict = body
        self._http_response = None


class _Client:
    def __init__(self, bodies):
        self.bodies = bodies

    def get(self, path, args=None, headers=None):
        return _Rest(self.bodies.get(path, {}))


class _Processor(BaseProcessorNormalizer):
    def memory_dimm_pattern(self, ctx):
        return re.compile(r"/Memory/")


class TestProcessorSummary(unittest.TestCase):
    def _summary(self, dimms):
        bodies = {MEM: {"Members": [{"@odata.id": f"{MEM}/{i}"} for i in dimms]}}
        bodies.update({f"{MEM}/{i}": d for i, d in dimms.items()})
        ctx = _ctx({"Id": "CPU1", "@odata.id": CPU}, _Client(bodies))
        _Processor().prefetch(ctx)
        return ctx.prefetched["memory_summary"]

    def test_dimms_without_a_scheme_leave_ecc_mode_null(self) -> None:
        got = self._summary({"1": {"CapacityMiB": 1024}, "2": {"CapacityMiB": 1024}})
        self.assertEqual(got["TotalMemorySizeMiB"], 2048)
        self.assertIsNone(got["ECCModeEnabled"])

    def test_reported_ecc_dimms_give_true(self) -> None:
        got = self._summary(
            {"1": {"CapacityMiB": 1024, "ErrorCorrection": "MultiBitECC"}}
        )
        self.assertIs(got["ECCModeEnabled"], True)


if __name__ == "__main__":
    unittest.main()
