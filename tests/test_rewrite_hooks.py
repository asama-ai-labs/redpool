# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Rewrite hooks share one normalization path and a typed call context."""

import dataclasses
import logging
from typing import Any, Dict

import pytest

from normalizers.apply import normalize_resource
from normalizers.base import ResourceNormalizer
from normalizers.chassis.network_adapters import hpe as hpe_adapter
from normalizers.request_rewrites import RewriteCall, get_request_rewrite
from normalizers.types import NormalizationContext
from redpool.proxy import RedfishProxy

TYPE_A = "#Thing.v1_0_0.Thing"
TYPE_B = "#Thing.v1_1_0.Thing"


class TinyNormalizer(ResourceNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        ctx.prefetched["suffix"] = "!"

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.type": TYPE_B,
            "Name": lambda ctx: ctx.data["Name"] + ctx.prefetched["suffix"],
            "Extra": "base",
        }

    def version_overrides(self) -> Dict[str, Dict[str, Any]]:
        return {TYPE_A: {"Extra": "override"}}


class TinyEntry:
    def for_vendor(self, vendor: str) -> ResourceNormalizer:
        return TinyNormalizer()


def _ctx(data: Dict[str, Any]) -> NormalizationContext:
    return NormalizationContext(
        data=data, client=None, logger=logging.getLogger("test"), vendor="HPE"
    )


def test_normalize_resource_applies_version_overrides():
    out = normalize_resource(
        TinyNormalizer(), _ctx({"@odata.type": TYPE_A, "Name": "n"})
    )
    assert out == {"@odata.type": TYPE_B, "Name": "n!", "Extra": "override"}


def test_normalize_resource_skips_overrides_for_other_types():
    out = normalize_resource(
        TinyNormalizer(), _ctx({"@odata.type": "#Thing.v9_9_9.Thing", "Name": "n"})
    )
    assert out["Extra"] == "base"


def test_proxy_normalize_resource_matches_normalize_resource():
    data = {"@odata.type": TYPE_A, "Name": "n"}
    proxy = RedfishProxy.__new__(RedfishProxy)
    proxy.logger = logging.getLogger("test")
    via_proxy = proxy._normalize_resource(data, TinyEntry(), "HPE", None)  # type: ignore[arg-type]
    assert via_proxy == normalize_resource(TinyNormalizer(), _ctx(data))


def test_rewrite_call_fields_and_frozen():
    call = RewriteCall("c", "/p", "/b", "/f", "/t")
    assert (call.client, call.path, call.backend_path) == ("c", "/p", "/b")
    assert (call.from_prefix, call.to_prefix) == ("/f", "/t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        call.path = "/x"  # type: ignore[misc]


class _Rest:
    def __init__(self, status: int, body: Dict[str, Any]) -> None:
        self.status = status
        self.dict = body
        self._http_response = None


class _Client:
    def __init__(self, bodies: Dict[str, Dict[str, Any]]) -> None:
        self.bodies = bodies

    def get(self, path, args=None, headers=None):
        if path in self.bodies:
            return _Rest(200, self.bodies[path])
        return _Rest(404, {})


def test_hpe_base_network_adapter_is_normalized_once(monkeypatch):
    path = "/redfish/v1/Chassis/1/NetworkAdapters/1"
    backend = "/redfish/v1/Systems/1/BaseNetworkAdapters/1"
    client = _Client(
        {
            "/redfish/v1/Chassis/1/NetworkAdapters": {"Members": [{"@odata.id": path}]},
            path + "/Ports": {"Members": []},
        }
    )
    calls = {"prefetch": 0, "field_map": 0}
    cls = hpe_adapter.HPEChassisNetworkAdapterNormalizer
    real_prefetch, real_field_map = cls.prefetch, cls.field_map

    def counting_prefetch(self, ctx):
        calls["prefetch"] += 1
        real_prefetch(self, ctx)

    def counting_field_map(self):
        calls["field_map"] += 1
        return real_field_map(self)

    monkeypatch.setattr(cls, "prefetch", counting_prefetch)
    monkeypatch.setattr(cls, "field_map", counting_field_map)

    resolved = get_request_rewrite("HPE", path, client=client)
    assert resolved is not None
    backend_path, from_prefix, to_prefix, rule = resolved
    assert backend_path == backend
    body = {
        "@odata.type": "#HpeBaseNetworkAdapter.v2_0_0.HpeBaseNetworkAdapter",
        "@odata.id": backend,
        "Id": "1",
        "Name": "nic",
        "PhysicalPorts": [],
    }
    assert rule.after_200_merge is not None and rule.should_normalize_single
    rule.after_200_merge(
        RewriteCall(client, path, backend_path, from_prefix, to_prefix), body
    )
    assert not rule.should_normalize_single(path, backend_path)
    assert calls == {"prefetch": 1, "field_map": 1}
