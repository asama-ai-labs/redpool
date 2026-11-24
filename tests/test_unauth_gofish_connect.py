# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""gofish Connect: unauth service root + session create must not 401 in Redpool."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from redpool.proxy import BmcAuthError, RedfishProxy


def _resp(status: int, body: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status = status
    r.dict = body
    # Mirror a real RestResponse: .dict is parsed from the same decoded text.
    r.text = json.dumps(body) if body is not None else ""
    r.getheader = MagicMock(return_value=None)
    r._http_response = None
    return r


class TestUnauthGofishConnect(unittest.TestCase):
    def test_header_get_case_insensitive(self) -> None:
        self.assertEqual(
            RedfishProxy._header_get({"authorization": "Basic abc"}, "Authorization"),
            "Basic abc",
        )
        self.assertEqual(
            RedfishProxy._header_get({"X-Auth-Token": "tok"}, "x-auth-token"),
            "tok",
        )

    def test_session_create_without_auth_headers_ignores_metadata_401(self) -> None:
        proxy = RedfishProxy()
        client = MagicMock()
        client.base_url = "https://192.0.2.10"
        client.post.return_value = _resp(
            201,
            {"Id": "1", "@odata.id": "/redfish/v1/SessionService/Sessions/1"},
        )
        client.post.return_value.getheader = MagicMock(
            side_effect=lambda n: {
                "x-auth-token": "session-tok",
                "location": "/redfish/v1/SessionService/Sessions/1",
            }.get((n or "").lower())
        )

        with (
            patch.object(
                proxy,
                "_get_or_create_backend_client",
                return_value=client,
            ),
            patch.object(
                proxy,
                "_extract_server_metadata",
                side_effect=BmcAuthError("BMC returned 401 for /redfish/v1/Systems"),
            ),
        ):
            body, _meta, status, norm_status, headers = proxy.proxy_request(
                path="/redfish/v1/SessionService/Sessions",
                method="POST",
                redfish_endpoint="https://192.0.2.10",
                body={"UserName": "admin", "Password": "secret"},
                headers={},  # gofish: credentials in body only
            )

        self.assertEqual(status, 201)
        self.assertEqual(norm_status, "passthrough")
        self.assertEqual(body.get("Id"), "1")
        self.assertEqual(headers.get("X-Auth-Token"), "session-tok")
        client.post.assert_called()

    def test_skip_path_service_root_without_auth_ignores_metadata_401(self) -> None:
        proxy = RedfishProxy()
        root = {
            "@odata.id": "/redfish/v1/",
            "RedfishVersion": "1.6.0",
            "Vendor": "HPE",
            "Product": "ProLiant DL380 Gen10",
        }
        client = MagicMock()
        client.base_url = "https://192.0.2.10"
        client.get.return_value = _resp(200, root)

        with (
            patch.object(
                proxy,
                "_get_or_create_backend_client",
                return_value=client,
            ),
            patch.object(
                proxy,
                "_extract_server_metadata",
                side_effect=AssertionError(
                    "skip_paths must not probe Systems metadata"
                ),
            ),
        ):
            body, meta, status, norm_status, _hdrs = proxy.proxy_request(
                path="/redfish/v1/",
                method="GET",
                redfish_endpoint="https://192.0.2.10",
                headers={},
            )

        self.assertEqual(status, 200)
        self.assertEqual(norm_status, "passthrough")
        self.assertEqual(body.get("RedfishVersion"), "1.6.0")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.vendor, "HPE")
        self.assertEqual(meta.model, "ProLiant DL380 Gen10")
        # Only the passthrough GET — no Systems probe.
        client.get.assert_called()
        for call in client.get.call_args_list:
            self.assertNotIn("Systems", call.args[0])

    def test_extract_system_model_401_returns_unknown(self) -> None:
        proxy = RedfishProxy()
        client = MagicMock()
        client.get.return_value = _resp(401, {"error": "NoValidSession"})
        self.assertEqual(proxy._extract_system_model(client), "unknown")

    def test_extract_metadata_uses_product_without_systems(self) -> None:
        proxy = RedfishProxy()
        root = {
            "Vendor": "HPE",
            "Product": "ProLiant DL380 Gen10",
            "Oem": {"Hpe": {}},
        }
        client = MagicMock()
        client.get.side_effect = lambda path, *a, **k: (
            _resp(200, root)
            if path.rstrip("/").endswith("redfish/v1")
            else (_ for _ in ()).throw(AssertionError(f"unexpected get {path}"))
        )
        meta = proxy._extract_server_metadata("https://192.0.2.10", client)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.vendor, "HPE")
        self.assertEqual(meta.model, "ProLiant DL380 Gen10")

    def test_extract_metadata_idrac_product_uses_system_model(self) -> None:
        """Dell Product is the BMC name. Memory maps need Systems.Model."""
        proxy = RedfishProxy()
        root = {
            "Product": "Integrated Dell Remote Access Controller",
            "Oem": {"Dell": {}},
        }
        system = {"Model": "PowerEdge R6525"}

        def _get(path, *a, **k):
            p = (path or "").rstrip("/")
            if p.endswith("redfish/v1"):
                return _resp(200, root)
            if p.endswith("/Systems"):
                return _resp(
                    200,
                    {
                        "Members": [
                            {"@odata.id": "/redfish/v1/Systems/System.Embedded.1"}
                        ]
                    },
                )
            if p.endswith("/Systems/System.Embedded.1"):
                return _resp(200, system)
            raise AssertionError(f"unexpected get {path}")

        client = MagicMock()
        client.get.side_effect = _get
        meta = proxy._extract_server_metadata("https://192.0.2.10", client)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.model, "PowerEdge R6525")
        cached = proxy.metadata_cache.get("metadata:https://192.0.2.10")
        self.assertEqual(cached.model, "PowerEdge R6525")

    def test_extract_metadata_does_not_cache_generic_idrac_product(self) -> None:
        proxy = RedfishProxy()
        root = {
            "Product": "Integrated Dell Remote Access Controller",
            "Oem": {"Dell": {}},
        }
        client = MagicMock()
        client.get.side_effect = lambda path, *a, **k: (
            _resp(200, root)
            if (path or "").rstrip("/").endswith("redfish/v1")
            else _resp(401, {"error": "NoValidSession"})
        )
        meta = proxy._extract_server_metadata("https://192.0.2.10", client)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.model, "Integrated Dell Remote Access Controller")
        key = "metadata:https://192.0.2.10"
        self.assertIsNone(proxy.metadata_cache.get(key))
        fallback = proxy._unresolved_metadata_cache.get(key)
        self.assertIsNotNone(fallback)
        self.assertEqual(fallback.model, "Integrated Dell Remote Access Controller")
        # Still inside the fallback TTL: do not probe Systems again.
        calls_after_first = client.get.call_count
        again = proxy._extract_server_metadata("https://192.0.2.10", client)
        self.assertEqual(again.model, "Integrated Dell Remote Access Controller")
        self.assertEqual(client.get.call_count, calls_after_first)

    def test_unresolved_metadata_expires_and_retries_systems(self) -> None:
        proxy = RedfishProxy()
        root = {
            "Product": "Integrated Dell Remote Access Controller",
            "Oem": {"Dell": {}},
        }
        system = {"Model": "PowerEdge R6525"}
        systems_allowed = {"ok": False}

        def _get(path, *a, **k):
            p = (path or "").rstrip("/")
            if p.endswith("redfish/v1"):
                return _resp(200, root)
            if not systems_allowed["ok"]:
                return _resp(401, {"error": "NoValidSession"})
            if p.endswith("/Systems"):
                return _resp(
                    200,
                    {
                        "Members": [
                            {"@odata.id": "/redfish/v1/Systems/System.Embedded.1"}
                        ]
                    },
                )
            if p.endswith("/Systems/System.Embedded.1"):
                return _resp(200, system)
            raise AssertionError(f"unexpected get {path}")

        client = MagicMock()
        client.get.side_effect = _get
        key = "metadata:https://192.0.2.10"
        first = proxy._extract_server_metadata("https://192.0.2.10", client)
        self.assertEqual(first.model, "Integrated Dell Remote Access Controller")
        proxy._unresolved_metadata_cache._ttl_seconds = -1
        systems_allowed["ok"] = True
        second = proxy._extract_server_metadata("https://192.0.2.10", client)
        self.assertEqual(second.model, "PowerEdge R6525")
        self.assertEqual(proxy.metadata_cache.get(key).model, "PowerEdge R6525")
        self.assertIsNone(proxy._unresolved_metadata_cache.get(key))

    def test_create_client_keeps_anonymous_and_authenticated_slots_separate(
        self,
    ) -> None:
        proxy = RedfishProxy()
        unauth = MagicMock()
        unauth.auth_scope = "anon"
        unauth.close = MagicMock()
        auth = MagicMock()
        auth.get_session_key.return_value = "tok"
        auth.get_authorization_key.return_value = None

        def wrap(**kw):
            kw["base_client"].auth_scope = kw["auth_scope"]
            return kw["base_client"]

        proxy.redfish_clients[("https://bmc", "anon")] = unauth
        with (
            patch("redpool.proxy.metrics.ACTIVE_BMC_CONNECTIONS") as m,
            patch("redpool.proxy.redfish.redfish_client", return_value=auth),
            patch("redpool.proxy.limit_session_to_one_connection"),
            patch("redpool.proxy.CachedRedfishClient", side_effect=wrap),
        ):
            m.inc = MagicMock()
            m.dec = MagicMock()
            got = proxy._create_client(
                base_url="https://bmc", sessionkey="tok", scope="c:scope1"
            )
        self.assertIs(got, auth)
        # The anonymous client is not replaced or closed by an authenticated request.
        unauth.close.assert_not_called()
        self.assertIs(proxy.redfish_clients[("https://bmc", "anon")], unauth)
        self.assertIs(proxy.redfish_clients[("https://bmc", "auth")], auth)


if __name__ == "__main__":
    unittest.main()
