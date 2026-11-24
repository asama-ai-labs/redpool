# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE and Intel EthernetInterfaces collections drop members the BMC cannot serve.

The collector fails a whole collection when one member fails, so one dead link hid every
interface on the system.
"""

import logging

from normalizers import get_collection_mapping
from redpool.proxy import RedfishProxy

PATH = "/redfish/v1/Systems/1/EthernetInterfaces"


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


def _normalize(vendor, members, live_ids, count=None):
    data = {"@odata.id": PATH, "Name": "Interfaces", "Members": members}
    if count is not None:
        data["Members@odata.count"] = count
    bodies = {f"{PATH}/{i}": {"Id": i} for i in live_ids}
    proxy = RedfishProxy.__new__(RedfishProxy)
    proxy.logger = logging.getLogger("t")
    return proxy.normalize_redfish_response(
        data,
        get_collection_mapping("Systems/EthernetInterfaces"),
        vendor,
        FakeClient(bodies),
        resource_path=PATH,
    )


def test_intel_drops_dead_members_and_recounts():
    members = [{"@odata.id": f"{PATH}/{i}"} for i in ("1", "2", "3", "4")]
    body = _normalize("Intel", members, live_ids=("1", "2"), count=4)
    assert body["Members"] == members[:2]
    assert body["Members@odata.count"] == 2


def test_hpe_repairs_blank_ids_then_drops_dead_members():
    members = [
        {"@odata.id": f"{PATH}/333"},
        {"@odata.id": "", "Id": "DE07A000"},
        {"@odata.id": f"{PATH}/5"},
    ]
    body = _normalize("HPE", members, live_ids=("333", "5"), count=3)
    assert body["Members"] == [
        {"@odata.id": f"{PATH}/333"},
        {"@odata.id": f"{PATH}/5"},
    ]
    assert body["Members@odata.count"] == 2


def test_hpe_keeps_a_blank_member_the_bmc_can_serve():
    members = [{"@odata.id": "", "Id": "DE07A000"}]
    body = _normalize("HPE", members, live_ids=("DE07A000",))
    assert body["Members"] == [{"@odata.id": f"{PATH}/DE07A000"}]
    assert "Members@odata.count" not in body


def test_other_vendors_keep_their_members():
    members = [{"@odata.id": f"{PATH}/1"}, {"@odata.id": f"{PATH}/2"}]
    body = _normalize("Dell", members, live_ids=("1",))
    assert body["Members"] == members


def test_prefetch_is_registered_only_for_vendors_that_need_it():
    mapping = get_collection_mapping("Systems/EthernetInterfaces")
    assert mapping.prefetch_for_vendor("HPE") is not None
    assert mapping.prefetch_for_vendor("Intel") is not None
    assert mapping.prefetch_for_vendor("Dell") is None
