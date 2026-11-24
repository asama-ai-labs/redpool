# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

import logging

from redpool.proxy import RedfishProxy, _apply_select


def test_select_keeps_named_and_odata_properties():
    body = {"@odata.id": "/x", "Name": "n", "Id": "1"}
    assert _apply_select(body, "/redfish/v1/Systems/1?$select=Name") == {
        "@odata.id": "/x",
        "Name": "n",
    }


def test_no_select_is_unchanged():
    body = {"@odata.id": "/x", "Name": "n"}
    assert _apply_select(body, "/redfish/v1/Systems?$top=2") == body


def test_query_string_does_not_affect_normalizer_lookup():
    class Client:
        def get_base_url(self):
            return "https://bmc"

    class DictCache:
        def __init__(self):
            self.d = {}

        def get(self, k):
            return self.d.get(k)

        def set(self, k, v):
            self.d[k] = v

    proxy = RedfishProxy.__new__(RedfishProxy)
    proxy.logger = logging.getLogger("t")
    proxy.objecttype_cache = DictCache()

    plain = proxy.get_normalizer_for_path("/redfish/v1/Systems", Client())
    assert plain is not None
    assert (
        proxy.get_normalizer_for_path("/redfish/v1/Systems?$expand=*", Client())
        is plain
    )
    assert not any("?" in k for k in proxy.objecttype_cache.d)
