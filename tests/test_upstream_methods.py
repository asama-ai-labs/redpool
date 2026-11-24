# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Upstream method forwarding: bodies reach the BMC; unknown methods never do."""

import unittest
import unittest.mock
from unittest.mock import MagicMock

from redpool.proxy import RedfishProxy

SETTINGS = "/redfish/v1/Systems/1/Bios/Settings"
BODY = {"Attributes": {"BootMode": "Uefi"}}


class FakeResponse:
    status = 200

    def __init__(self, body=None):
        self.dict = body if body is not None else {"ok": True}


class UpstreamMethodTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proxy = RedfishProxy()
        self.client = MagicMock()
        for verb in ("get", "post", "put", "patch", "delete"):
            getattr(self.client, verb).return_value = FakeResponse()

    def test_patch_sends_body(self) -> None:
        status = self.proxy._fetch_upstream(self.client, SETTINGS, "PATCH", BODY)[1]
        self.assertEqual(status, 200)
        self.client.patch.assert_called_once_with(SETTINGS, body=BODY, max_retry=0)

    def test_lowercase_patch_sends_body(self) -> None:
        self.proxy._fetch_upstream(self.client, SETTINGS, "patch", BODY)
        self.client.patch.assert_called_once_with(SETTINGS, body=BODY, max_retry=0)

    def test_post_and_put_send_body(self) -> None:
        self.proxy._fetch_upstream(self.client, SETTINGS, "POST", BODY)
        self.client.post.assert_called_once_with(SETTINGS, body=BODY, max_retry=0)
        self.proxy._fetch_upstream(self.client, SETTINGS, "PUT", BODY)
        self.client.put.assert_called_once_with(SETTINGS, body=BODY, max_retry=0)

    def test_writes_are_never_retried(self) -> None:
        for verb in ("post", "put", "patch", "delete"):
            with self.subTest(verb=verb):
                self.proxy._fetch_upstream(self.client, SETTINGS, verb.upper(), BODY)
                kwargs = getattr(self.client, verb).call_args.kwargs
                self.assertEqual(kwargs.get("max_retry"), 0)

    def test_json_bytes_body_is_sent_as_json(self) -> None:
        raw = b'{"Attributes": {"BootMode": "Uefi"}}'
        self.proxy._fetch_upstream(
            self.client,
            SETTINGS,
            "PATCH",
            raw,
            {"content-type": "application/json"},
        )
        self.assertEqual(self.client.patch.call_args.kwargs["body"], BODY)

    def test_non_json_content_type_body_is_sent_unchanged(self) -> None:
        raw = b"\x00\x01binary"
        self.proxy._fetch_upstream(
            self.client,
            SETTINGS,
            "POST",
            raw,
            {"Content-Type": "application/octet-stream"},
        )
        self.assertEqual(self.client.post.call_args.kwargs["body"], raw)

    def test_conditional_headers_are_forwarded_on_writes(self) -> None:
        self.proxy._fetch_upstream(
            self.client,
            SETTINGS,
            "PATCH",
            BODY,
            {"if-match": 'W/"abc"', "If-None-Match": "*", "Cookie": "secret"},
        )
        self.assertEqual(
            self.client.patch.call_args.kwargs["headers"],
            {"If-Match": 'W/"abc"', "If-None-Match": "*"},
        )

    def test_get_keeps_default_retries_and_sends_no_headers(self) -> None:
        self.proxy._fetch_upstream(
            self.client, SETTINGS, "GET", None, {"If-Match": "x"}
        )
        self.client.get.assert_called_once_with(SETTINGS)

    def test_session_create_uses_single_attempt(self) -> None:
        sessions = "/redfish/v1/SessionService/Sessions"
        self.proxy._fetch_upstream(
            self.client, sessions, "POST", {"UserName": "u", "Password": "p"}
        )
        kwargs = self.client.post.call_args.kwargs
        self.assertEqual(kwargs.get("max_retry"), 0)

    def test_body_free_methods_send_no_body(self) -> None:
        self.proxy._fetch_upstream(self.client, SETTINGS, "GET", None)
        self.client.get.assert_called_once_with(SETTINGS)
        self.proxy._fetch_upstream(self.client, SETTINGS, "DELETE", None)
        self.client.delete.assert_called_once_with(SETTINGS, max_retry=0)

    def test_body_free_method_ignores_stray_body(self) -> None:
        self.proxy._fetch_upstream(self.client, SETTINGS, "DELETE", BODY)
        self.client.delete.assert_called_once_with(SETTINGS, max_retry=0)

    def test_unknown_methods_are_refused_and_not_forwarded(self) -> None:
        for verb in (
            "TRACE",
            "OPTIONS",
            "HEAD",
            "CONNECT",
            "LOGIN",
            "CLOSE",
            "get_session",
        ):
            with self.subTest(verb=verb):
                body, status, headers = self.proxy._fetch_upstream(
                    self.client, SETTINGS, verb, BODY
                )
                self.assertIsNone(body)
                self.assertEqual(status, 405)
                self.assertEqual(headers, {})
        self.assertEqual(self.client.method_calls, [])


class WriteResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        from redpool.proxy import ServerMetadata

        self.proxy = RedfishProxy()
        self.meta = ServerMetadata(hostname="192.0.2.10", vendor="HPE", model="X")

    def _build(self, method: str):
        return self.proxy._build_proxy_response(
            {"Status": "ok"},
            200,
            "/redfish/v1/Systems/1",
            self.meta,
            MagicMock(),
            "192.0.2.10",
            "HPE",
            "X",
            method,
            0.0,
        )

    def test_write_response_is_not_normalized_as_a_resource(self) -> None:
        for method in ("PATCH", "POST", "PUT", "DELETE"):
            with self.subTest(method=method):
                body, _meta, status, norm = self._build(method)
                self.assertEqual(body, {"Status": "ok"})
                self.assertEqual((status, norm), (200, "passthrough"))

    def test_auth_error_on_a_write_is_not_replayed(self) -> None:
        client = MagicMock()
        client.patch.return_value = type("R", (), {"status": 401, "dict": {}})()
        with (
            unittest.mock.patch.object(
                self.proxy, "_recycle_client_on_auth_error", return_value=True
            ),
            unittest.mock.patch.object(self.proxy, "_drop_client") as drop,
        ):
            _body, status, _client, _h = self.proxy._fetch_upstream_recoverable(
                "https://192.0.2.10",
                {"Authorization": "x"},
                client,
                SETTINGS,
                "PATCH",
                BODY,
            )
        self.assertEqual(status, 401)
        self.assertEqual(client.patch.call_count, 1)
        drop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
