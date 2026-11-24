# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Tests that a request never runs on another caller's BMC credentials."""

import base64
import logging
import unittest
from unittest.mock import MagicMock, patch

from redpool.cache import InMemoryCache
from redpool.proxy import RedfishProxy
from redpool.redfish_client import CachedRedfishClient

BASE = "https://bmc.example.invalid"


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.dict = body


class FakeBase:
    """Stands in for the python-redfish client; records GETs and its session."""

    def __init__(self, base_url):
        self._base_url = base_url
        self._session = MagicMock()
        self.get_calls = 0

    def get_base_url(self):
        return self._base_url

    def login(self, auth=None):
        return None

    def get(self, path, args=None, headers=None):
        self.get_calls += 1
        return FakeResponse({"path": path, "call": self.get_calls})


class CredentialScopingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.created: list = []

        def factory(**kwargs):
            base = FakeBase(kwargs["base_url"])
            self.created.append(base)
            return base

        self.patches = [
            patch("redpool.proxy.redfish.redfish_client", side_effect=factory),
            patch("redpool.proxy.limit_session_to_one_connection"),
        ]
        for p in self.patches:
            p.start()
        self.proxy = RedfishProxy()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()

    def test_anonymous_request_never_gets_authenticated_client(self) -> None:
        authed = self.proxy._get_or_create_backend_client(
            BASE, _basic("admin", "secret")
        )
        anon = self.proxy._get_or_create_backend_client(BASE, None)
        self.assertIsNot(anon, authed)
        self.assertEqual(anon.auth_scope, "anon")
        self.assertNotEqual(authed.auth_scope, "anon")

    def test_same_credential_reuses_client(self) -> None:
        first = self.proxy._get_or_create_backend_client(
            BASE, _basic("admin", "secret")
        )
        second = self.proxy._get_or_create_backend_client(
            BASE, _basic("admin", "secret")
        )
        self.assertIs(first, second)
        self.assertEqual(len(self.created), 1)

    def test_different_credential_gets_its_own_client_and_closes_previous(self) -> None:
        admin = self.proxy._get_or_create_backend_client(
            BASE, _basic("admin", "secret")
        )
        other = self.proxy._get_or_create_backend_client(BASE, _basic("admin", "wrong"))
        self.assertIsNot(admin, other)
        self.assertNotEqual(admin.auth_scope, other.auth_scope)
        # The replaced session is closed, so it cannot be used by mistake later.
        self.created[0]._session.close.assert_called()
        # The admin client is no longer the one serving BMC requests.
        self.assertIs(self.proxy.redfish_clients[(BASE, "auth")], other)

    def test_wrong_password_request_does_not_run_on_valid_session(self) -> None:
        admin = self.proxy._get_or_create_backend_client(
            BASE, _basic("admin", "secret")
        )
        wrong = self.proxy._get_or_create_backend_client(BASE, _basic("admin", "nope"))
        self.assertIsNot(wrong, admin)
        self.assertEqual(
            wrong.auth_scope, RedfishProxy._auth_scope(_basic("admin", "nope"))
        )

    def test_scopes_differ_by_credential_and_hide_the_secret(self) -> None:
        scope_basic = RedfishProxy._auth_scope({"Authorization": "Basic c2VjcmV0"})
        scope_token = RedfishProxy._auth_scope({"X-Auth-Token": "c2VjcmV0"})
        self.assertNotEqual(scope_basic, scope_token)
        for scope in (scope_basic, scope_token):
            self.assertNotIn("c2VjcmV0", scope)
        # Header names are case-insensitive, and the scope is stable across calls.
        self.assertEqual(
            RedfishProxy._auth_scope({"authorization": "Basic c2VjcmV0"}), scope_basic
        )
        self.assertEqual(RedfishProxy._auth_scope(None), "anon")
        self.assertEqual(RedfishProxy._auth_scope({}), "anon")

    def test_token_is_preferred_over_basic_auth_for_scope(self) -> None:
        both = RedfishProxy._auth_scope(
            {"X-Auth-Token": "tok", "Authorization": "Basic x"}
        )
        token_only = RedfishProxy._auth_scope({"X-Auth-Token": "tok"})
        self.assertEqual(both, token_only)

    def test_cached_response_is_not_served_across_scopes(self) -> None:
        cache = InMemoryCache(ttl_seconds=60, name="scope-test")
        base = FakeBase(BASE)
        logger = logging.getLogger("test.scope")
        admin = CachedRedfishClient(base, cache, logger, auth_scope="c:admin")
        anon = CachedRedfishClient(base, cache, logger, auth_scope="anon")

        admin.get("/redfish/v1/Systems/1")
        self.assertEqual(base.get_calls, 1)
        # Same path, different scope: must hit the BMC, not the admin's cached body.
        anon.get("/redfish/v1/Systems/1")
        self.assertEqual(base.get_calls, 2)
        # Same scope again: served from cache.
        admin.get("/redfish/v1/Systems/1")
        self.assertEqual(base.get_calls, 2)


class CacheSweepTests(unittest.TestCase):
    def test_set_removes_expired_entries_that_are_never_read_again(self) -> None:
        with patch("redpool.cache.time.time", return_value=0.0):
            cache = InMemoryCache(ttl_seconds=10, name="sweep-test")
            cache.set("stale", 1)
        with patch("redpool.cache.time.time", return_value=20.0):
            cache.set("fresh", 2)
        self.assertNotIn("stale", cache._cache)
        self.assertIn("fresh", cache._cache)


if __name__ == "__main__":
    unittest.main()
