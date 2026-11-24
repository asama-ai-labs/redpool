# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Intel chassis ``Links.Contains`` drops entries the BMC answers with an error."""

import logging
import unittest

from normalizers.evaluator import evaluate
from normalizers.chassis.intel import IntelChassisNormalizer
from normalizers.types import NormalizationContext

ROOT = "/redfish/v1/Chassis/RackMount"


class FakeRest:
    def __init__(self, status, body):
        self.status = status
        self.dict = body
        self._http_response = None


class FakeClient:
    def __init__(self, bodies):
        self.bodies = bodies

    def get(self, path, args=None, headers=None):
        if path not in self.bodies:
            return FakeRest(404, {"error": {"code": "GeneralError"}})
        return FakeRest(200, self.bodies[path])


def _normalize(contains, bodies, count=None):
    links = {"Contains": [{"@odata.id": u} for u in contains]}
    if count is not None:
        links["Contains@odata.count"] = count
    ctx = NormalizationContext(
        data={"Id": "RackMount", "Name": "RackMount", "Links": links},
        client=FakeClient(bodies),
        logger=logging.getLogger("t"),
        vendor="Intel",
        resource_path=ROOT,
    )
    normalizer = IntelChassisNormalizer()
    normalizer.prefetch(ctx)
    return evaluate(normalizer.field_map(), ctx)["Links"]


class IntelChassisContainsTests(unittest.TestCase):
    def test_missing_child_is_dropped_and_order_kept(self) -> None:
        a, b, c = f"{ROOT}/A", f"{ROOT}/Gone", f"{ROOT}/C"
        links = _normalize([a, b, c], {a: {"Id": "A"}, c: {"Id": "C"}}, count=3)
        self.assertEqual(links["Contains"], [{"@odata.id": a}, {"@odata.id": c}])
        self.assertEqual(links["Contains@odata.count"], 2)

    def test_all_children_present_is_unchanged(self) -> None:
        a = f"{ROOT}/A"
        links = _normalize([a], {a: {"Id": "A"}})
        self.assertEqual(links["Contains"], [{"@odata.id": a}])
        self.assertNotIn("Contains@odata.count", links)


if __name__ == "__main__":
    unittest.main()
