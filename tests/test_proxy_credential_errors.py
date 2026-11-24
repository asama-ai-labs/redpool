# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Wrong or malformed credentials answer 401, never 500, and never retry the login."""

from __future__ import annotations

import base64
import unittest
from unittest.mock import MagicMock, patch

from redfish.rest.v1 import InvalidCredentialsError

from redpool.proxy import BmcAuthError, BmcCredentialsError, RedfishProxy

BMC = "https://192.0.2.1"


def _basic(user_pass: str) -> str:
    return "Basic " + base64.b64encode(user_pass.encode()).decode()


class TestBasicCredentialParsing(unittest.TestCase):
    def test_valid_header_gives_username_and_password(self) -> None:
        self.assertEqual(
            RedfishProxy._basic_credentials(_basic("admin:p:ss")), ("admin", "p:ss")
        )
        self.assertEqual(
            RedfishProxy._basic_credentials("basic " + _basic("a:b")[6:]), ("a", "b")
        )

    def test_unparseable_headers_are_credential_errors(self) -> None:
        for header in (
            "Bearer abc123",
            "Basic",
            "Basic !!!not-base64!!!",
            _basic("no-colon-here"),
            "Basic " + base64.b64encode(b"\xff\xfe:x").decode(),
        ):
            with self.subTest(header=header):
                with self.assertRaises(BmcCredentialsError) as caught:
                    RedfishProxy._basic_credentials(header)
                self.assertNotIn(header, str(caught.exception))

    def test_credential_error_is_an_auth_error(self) -> None:
        self.assertTrue(issubclass(BmcCredentialsError, BmcAuthError))


class TestCredentialErrorsAnswer401(unittest.TestCase):
    def _request(self, proxy: RedfishProxy, authorization: str):
        return proxy.proxy_request(
            path="/redfish/v1/Systems",
            method="GET",
            redfish_endpoint=BMC,
            headers={"Authorization": authorization},
            body=None,
            passthrough_logs=False,
        )

    def test_malformed_authorization_header_is_401(self) -> None:
        proxy = RedfishProxy()
        for header in ("Bearer abc123", "Basic", "Basic !!!not-base64!!!"):
            with self.subTest(header=header):
                body, _meta, status, norm_status, _headers = self._request(
                    proxy, header
                )
                self.assertEqual(status, 401)
                self.assertEqual(norm_status, "error")
                self.assertIsNone(body)

    def test_wrong_password_is_401_after_one_login(self) -> None:
        proxy = RedfishProxy()
        client = MagicMock()
        client.login.side_effect = InvalidCredentialsError("bad password")
        with patch("redpool.proxy.redfish.redfish_client", return_value=client):
            body, _meta, status, norm_status, _headers = self._request(
                proxy, _basic("admin:wrong")
            )
        self.assertEqual(status, 401)
        self.assertEqual(norm_status, "error")
        self.assertIsNone(body)
        self.assertEqual(client.login.call_count, 1)

    def test_rejected_client_is_not_cached(self) -> None:
        proxy = RedfishProxy()
        client = MagicMock()
        client.login.side_effect = InvalidCredentialsError("bad password")
        with patch("redpool.proxy.redfish.redfish_client", return_value=client):
            self._request(proxy, _basic("admin:wrong"))
        self.assertEqual(proxy.redfish_clients, {})


if __name__ == "__main__":
    unittest.main()
