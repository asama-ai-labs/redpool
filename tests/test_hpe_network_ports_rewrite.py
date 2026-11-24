# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Tests for HPE chassis Ports members: members without an @odata.id are dropped."""

from __future__ import annotations

from normalizers.chassis.network_adapters.hpe_chassis_network_rewrite import (
    _hpe_chassis_network_after_200_merge,
    drop_phantom_network_port_members,
)
from normalizers.request_rewrites import RewriteCall


def test_after_merge_drops_members_with_blank_odata_id():
    body = {
        "@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters/DA000000/Ports",
        "Members@odata.count": 2,
        "Members": [
            {"@odata.id": "", "Id": "0"},
            {
                "@odata.id": "/redfish/v1/Chassis/1/NetworkAdapters/DA000000/Ports/1",
            },
        ],
    }
    out = drop_phantom_network_port_members(body)
    assert isinstance(out, dict)
    members = out.get("Members")
    assert isinstance(members, list)
    assert len(members) == 1
    assert members[0]["@odata.id"] == (
        "/redfish/v1/Chassis/1/NetworkAdapters/DA000000/Ports/1"
    )
    assert out.get("Members@odata.count") == 1


def test_port_settings_rewrite_uses_port_link_status_and_preserves_settings_fields():
    port = "/redfish/v1/Chassis/1/NetworkAdapters/DA000000/Ports/1"
    path = port + "/Settings"
    call = RewriteCall(None, path, path, path, path)
    body = {
        "@odata.type": "#Port.v1_9_0.Port",
        "@odata.id": path,
        "LinkStatus": "Up",
        "LinkConfiguration": [{"AutoSpeedNegotiationEnabled": True}],
    }

    out = _hpe_chassis_network_after_200_merge(call, body)

    assert out["@odata.type"] == "#Port.v1_20_0.Port"
    assert out["@odata.id"] == path
    assert out["LinkStatus"] == "LinkUp"
    assert out["LinkConfiguration"] == [{"AutoSpeedNegotiationEnabled": True}]
