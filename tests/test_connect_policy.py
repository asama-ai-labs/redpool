# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""CONNECT tunnels and raw TCP flows obey the target policy."""

import unittest
from unittest.mock import MagicMock, patch

from mitmproxy.test import tflow

from redpool import mitm_proxy
from redpool.access import TargetPolicy


def _connect(host: str, port: int = 443):
    flow = tflow.tflow()
    flow.request.method = "CONNECT"
    flow.request.host = host
    flow.request.port = port
    return flow


class ConnectPolicyTests(unittest.TestCase):
    def _policy(self, allowed):
        return patch.object(
            mitm_proxy, "target_policy", TargetPolicy(allowed_targets=allowed)
        )

    def test_connect_to_disallowed_host_is_refused(self) -> None:
        flow = _connect("127.0.0.1", 18999)
        with (
            self._policy(["10.99.99.99"]),
            patch.object(mitm_proxy, "REDPOOL_BACKEND_URL", ""),
        ):
            mitm_proxy.http_connect(flow)
        self.assertEqual(flow.response.status_code, 403)
        self.assertEqual(flow.response.headers["X-Redpool-Status"], "denied")

    def test_connect_to_allowed_host_passes(self) -> None:
        flow = _connect("10.99.99.99")
        flow.response = None
        with (
            self._policy(["10.99.99.99"]),
            patch.object(mitm_proxy, "REDPOOL_BACKEND_URL", ""),
        ):
            mitm_proxy.http_connect(flow)
        self.assertIsNone(flow.response)

    def test_tcp_flow_is_killed(self) -> None:
        flow = MagicMock()
        mitm_proxy.tcp_start(flow)
        flow.kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
