# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Session create passthrough must forward X-Auth-Token and Location."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch

from redpool.mitm_proxy import request as mitm_request
from redpool.proxy import RedfishProxy, ServerMetadata


class _SessionCreateClient:
    """Minimal backend client for POST SessionService/Sessions."""

    base_url = "https://mock-bmc.example.com"

    def __init__(self) -> None:
        self.last_post_kwargs: dict = {}

    def post(self, path, body=None, **kwargs):
        self.last_post_kwargs = kwargs
        assert path.rstrip("/") == "/redfish/v1/SessionService/Sessions"
        resp = MagicMock()
        resp.status = 201
        resp.dict = {
            "@odata.id": "/redfish/v1/SessionService/Sessions/1",
            "Id": "1",
            "UserName": "admin",
        }
        resp.text = json.dumps(resp.dict)
        headers = {
            "x-auth-token": "test-session-token",
            "location": "/redfish/v1/SessionService/Sessions/1",
        }

        def _getheader(name: str):
            if not name:
                return None
            return headers.get(name.lower())

        resp.getheader = _getheader
        resp._http_response = None
        return resp


class TestSessionCreatePassthroughHeaders(unittest.TestCase):
    def test_proxy_request_returns_session_headers_on_post(self) -> None:
        proxy = RedfishProxy()
        meta = ServerMetadata(
            hostname="mock-bmc.example.com",
            vendor="HPE",
            model="ProLiant",
        )
        client = _SessionCreateClient()
        body, _meta, status, norm_status, headers = proxy.proxy_request(
            path="/redfish/v1/SessionService/Sessions",
            method="POST",
            backend_client=client,
            server_metadata=meta,
            body={"UserName": "admin", "Password": "password"},
            headers={"Authorization": "Basic YWRtaW46cGFzc3dvcmQ="},
        )
        self.assertEqual(status, 201)
        self.assertEqual(norm_status, "passthrough")
        self.assertIsInstance(body, dict)
        self.assertEqual(body.get("Id"), "1")
        self.assertEqual(headers.get("X-Auth-Token"), "test-session-token")
        self.assertEqual(
            headers.get("Location"),
            "/redfish/v1/SessionService/Sessions/1",
        )
        # Non-idempotent session create must not inherit client max_retry=2.
        self.assertEqual(client.last_post_kwargs.get("max_retry"), 0)

    def test_mitm_response_includes_session_headers(self) -> None:
        proxy = RedfishProxy()
        meta = ServerMetadata(
            hostname="192.0.2.10",
            vendor="HPE",
            model="ProLiant",
        )
        upstream = (
            {"Id": "1"},
            meta,
            201,
            "passthrough",
            {
                "X-Auth-Token": "tok-from-bmc",
                "Location": "/redfish/v1/SessionService/Sessions/9",
            },
        )
        flow = MagicMock()
        flow.request.pretty_url = (
            "https://192.0.2.10/redfish/v1/SessionService/Sessions"
        )
        flow.request.path = "/redfish/v1/SessionService/Sessions"
        flow.request.method = "POST"
        flow.request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        flow.request.content = b'{"UserName":"user","Password":"pass"}'
        flow.response = None

        with (
            patch("redpool.mitm_proxy.redfish_proxy", proxy),
            patch.object(proxy, "proxy_request", return_value=upstream),
        ):
            asyncio.run(mitm_request(flow))

        self.assertIsNotNone(flow.response)
        self.assertEqual(flow.response.status_code, 201)
        # mitmproxy MultiDict-ish: compare via get
        self.assertEqual(flow.response.headers.get("X-Auth-Token"), "tok-from-bmc")
        self.assertEqual(
            flow.response.headers.get("Location"),
            "/redfish/v1/SessionService/Sessions/9",
        )
        self.assertEqual(flow.response.headers.get("X-Redpool-Status"), "passthrough")
        payload = json.loads(flow.response.content.decode("utf-8"))
        self.assertEqual(payload.get("Id"), "1")


if __name__ == "__main__":
    unittest.main()
