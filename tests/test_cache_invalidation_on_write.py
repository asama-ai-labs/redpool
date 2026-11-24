# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

import logging

from redpool.cache import InMemoryCache
from redpool.redfish_client import CachedRedfishClient


class _Resp:
    def __init__(self, body):
        self.status = 200
        self.dict = body


class _Base:
    def __init__(self):
        self.value = "old"
        self.calls = []

    def get_base_url(self):
        return "https://bmc"

    def get(self, path, args=None, headers=None):
        return _Resp({"v": self.value})

    def patch(self, path, body=None, **kw):
        self.calls.append(("patch", path))
        self.value = "new"
        return _Resp({})


def _client():
    base = _Base()
    cache = InMemoryCache(ttl_seconds=60)
    c = CachedRedfishClient(base, cache, logging.getLogger("t"), auth_scope="a")
    return base, cache, c


def test_patch_invalidates_path_and_parent_across_scopes():
    base, cache, c = _client()
    other = CachedRedfishClient(base, cache, logging.getLogger("t"), auth_scope="b")
    for path in ("/redfish/v1/Systems/1", "/redfish/v1/Systems", "/redfish/v1/Chassis"):
        c.get(path)
        other.get(path)
    assert c.get("/redfish/v1/Systems/1").dict["v"] == "old"

    c.patch("/redfish/v1/Systems/1", body={"x": 1})

    assert base.calls == [("patch", "/redfish/v1/Systems/1")]
    assert c.get("/redfish/v1/Systems/1").dict["v"] == "new"
    assert other.get("/redfish/v1/Systems/1").dict["v"] == "new"
    assert c.get("/redfish/v1/Systems").dict["v"] == "new"
    # Unrelated path stays cached.
    base.value = "changed"
    assert c.get("/redfish/v1/Chassis").dict["v"] == "old"


def test_task_and_update_service_not_cached():
    _, _, c = _client()
    assert not c._is_cacheable("/redfish/v1/TaskService/Tasks/1")
    assert not c._is_cacheable("/redfish/v1/UpdateService")


def test_patch_invalidates_cached_queries_of_the_path_and_its_parent():
    base, cache, c = _client()
    for path in (
        "/redfish/v1/Systems/1?$select=Id",
        "/redfish/v1/Systems?$expand=*",
        "/redfish/v1/Systems/10?$select=Id",  # a different resource, must stay cached
    ):
        c.get(path)

    c.patch("/redfish/v1/Systems/1", body={"x": 1})

    assert c.get("/redfish/v1/Systems/1?$select=Id").dict["v"] == "new"
    assert c.get("/redfish/v1/Systems?$expand=*").dict["v"] == "new"
    base.value = "changed"
    assert c.get("/redfish/v1/Systems/10?$select=Id").dict["v"] == "old"


class _Xml:
    """A 200 whose body is XML: not a JSON object."""

    status = 200
    dict: object = None
    text = "<edmx:Edmx/>"


class _Fixed(_Base):
    """A BMC that answers every GET with one given response."""

    def __init__(self, response):
        super().__init__()
        self._response = response

    def get(self, path, args=None, headers=None):
        return self._response


def _client_for(response):
    return CachedRedfishClient(
        _Fixed(response),
        InMemoryCache(ttl_seconds=60),
        logging.getLogger("t"),
        auth_scope="a",
    )


def test_non_json_body_is_passed_through_and_not_cached():
    xml = _Xml()
    c = _client_for(xml)
    assert c.get("/redfish/v1/$metadata") is xml
    assert c.get("/redfish/v1/$metadata") is xml  # still the upstream response, not {}


def test_json_array_body_is_passed_through_and_not_cached():
    resp = _Resp([1, 2])
    assert _client_for(resp).get("/redfish/v1/Things") is resp


def test_a_request_with_query_args_or_headers_is_not_cached():
    base, _, c = _client()
    c.get("/redfish/v1/Systems/1", args={"$select": "Id"})
    base.value = "newer"
    assert c.get("/redfish/v1/Systems/1", args={"$select": "Id"}).dict["v"] == "newer"
    assert c.get("/redfish/v1/Systems/1", headers={"X-A": "b"}).dict["v"] == "newer"
