# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Tests for per-BMC connection limiting (pool size 1 + I/O lock)."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock

from redpool.proxy import RedfishProxy
from redpool.redfish_client import (
    limit_session_to_one_connection,
    release_rest_response,
)


class TestBmcConnectionLimit(unittest.TestCase):
    def test_session_passthrough_path_detection(self) -> None:
        self.assertTrue(
            RedfishProxy._is_session_passthrough_path(
                "/redfish/v1/SessionService/Sessions"
            )
        )
        self.assertTrue(
            RedfishProxy._is_session_passthrough_path("/redfish/v1/Sessions")
        )
        self.assertFalse(
            RedfishProxy._is_session_passthrough_path("/redfish/v1/Systems")
        )

    def test_bmc_io_lock_stable_per_url(self) -> None:
        proxy = RedfishProxy()
        a = proxy._bmc_io_lock("https://bmc-a")
        b = proxy._bmc_io_lock("https://bmc-a")
        c = proxy._bmc_io_lock("https://bmc-b")
        self.assertIs(a, b)
        self.assertIsNot(a, c)
        self.assertIsInstance(a, type(threading.RLock()))

    def test_limit_session_mounts_pool_maxsize_one(self) -> None:
        session = MagicMock()
        session.headers = {}
        client = MagicMock()
        client._session = session
        limit_session_to_one_connection(client)
        self.assertEqual(session.headers.get("Connection"), "keep-alive")
        self.assertEqual(session.mount.call_count, 2)
        schemes = {call.args[0] for call in session.mount.call_args_list}
        self.assertEqual(schemes, {"http://", "https://"})
        for call in session.mount.call_args_list:
            adapter = call.args[1]
            self.assertEqual(adapter._pool_connections, 1)
            self.assertEqual(adapter._pool_maxsize, 1)

    def test_release_rest_response_prefers_release_conn(self) -> None:
        raw = MagicMock()
        http_resp = MagicMock()
        http_resp._content_consumed = True
        http_resp.raw = raw
        rest = MagicMock()
        rest._http_response = http_resp
        release_rest_response(rest)
        raw.release_conn.assert_called_once()
        http_resp.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
