# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Tests for shard parent Prometheus HTTP SD."""

import unittest

from redpool.shard_parent_admin import (
    _sd_target_hostport,
    prometheus_http_sd_payload,
)


class TestShardParentAdmin(unittest.TestCase):
    def test_sd_target_hostport_ipv4(self) -> None:
        self.assertEqual(_sd_target_hostport("127.0.0.1", 9101), "127.0.0.1:9101")

    def test_sd_target_hostport_ipv6(self) -> None:
        self.assertEqual(_sd_target_hostport("::1", 9101), "[::1]:9101")
        self.assertEqual(_sd_target_hostport("[::1]", 9101), "[::1]:9101")

    def test_prometheus_http_sd_payload(self) -> None:
        payload = prometheus_http_sd_payload("127.0.0.1", [9101, 9102])
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[0]["targets"], ["127.0.0.1:9101"])
        self.assertEqual(payload[0]["labels"]["redpool_shard"], "0")
        self.assertEqual(payload[1]["targets"], ["127.0.0.1:9102"])
        self.assertEqual(payload[1]["labels"]["redpool_shard"], "1")
        self.assertIn("job", payload[0]["labels"])

    def test_non_loopback_bind_warns(self) -> None:
        from redpool.shard_parent_admin import _log_admin_bind

        with self.assertLogs("redpool.shard_parent_admin", level="WARNING") as logs:
            _log_admin_bind("0.0.0.0", 9090)
        self.assertTrue(any("not loopback" in line for line in logs.output))

    def test_loopback_bind_is_info(self) -> None:
        from redpool.shard_parent_admin import _log_admin_bind

        with self.assertLogs("redpool.shard_parent_admin", level="INFO") as logs:
            _log_admin_bind("127.0.0.1", 9090)
        self.assertTrue(any("127.0.0.1:9090" in line for line in logs.output))
        self.assertFalse(any("WARNING" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
