# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Intel storage ``Drives`` drops entries the BMC answers with an error."""

import logging
import unittest

from normalizers.evaluator import evaluate
from normalizers.systems.storage.intel import IntelStorageNormalizer
from normalizers.types import NormalizationContext

STORAGE = "/redfish/v1/Systems/S/Storage/1"


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


def _normalize(drives, bodies, count=None):
    data = {"Id": "1", "Name": "Storage", "Drives": [{"@odata.id": u} for u in drives]}
    if count is not None:
        data["Drives@odata.count"] = count
    ctx = NormalizationContext(
        data=data,
        client=FakeClient(bodies),
        logger=logging.getLogger("t"),
        vendor="Intel",
        resource_path=STORAGE,
    )
    normalizer = IntelStorageNormalizer()
    normalizer.prefetch(ctx)
    return evaluate(normalizer.field_map(), ctx)


class IntelStorageDrivesTests(unittest.TestCase):
    def test_missing_drives_are_dropped(self) -> None:
        a, b = f"{STORAGE}/Drives/0", f"{STORAGE}/Drives/1"
        out = _normalize([a, b], {a: {"Id": "0"}}, count=2)
        self.assertEqual(out["Drives"], [{"@odata.id": a}])
        self.assertEqual(out["Drives@odata.count"], 1)

    def test_all_drives_missing_gives_empty_list(self) -> None:
        a = f"{STORAGE}/Drives/0"
        out = _normalize([a], {})
        self.assertEqual(out["Drives"], [])
        self.assertNotIn("Drives@odata.count", out)

    def test_all_present_is_unchanged(self) -> None:
        a = f"{STORAGE}/Drives/0"
        out = _normalize([a], {a: {"Id": "0"}})
        self.assertEqual(out["Drives"], [{"@odata.id": a}])


if __name__ == "__main__":
    unittest.main()
