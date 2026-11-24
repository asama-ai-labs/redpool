# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Tests for shared shard mitmdump argv builder."""

import unittest

from redpool.shard_mitm import mitmdump_worker_argv, mitmdump_worker_environ


class TestShardMitm(unittest.TestCase):
    def test_listen_port_and_metrics_from_index(self) -> None:
        argv = mitmdump_worker_argv(
            3,
            worker_host="127.0.0.1",
            worker_port_base=18080,
            metrics_port_base=9100,
            mitm_args=["-k"],
        )
        self.assertIn("--set", argv)
        self.assertIn("listen_port=18083", argv)
        self.assertIn("listen_host=127.0.0.1", argv)
        self.assertIn("connection_strategy=lazy", argv)
        self.assertIn("-k", argv)

    def test_environ_sets_metrics_port(self) -> None:
        env = mitmdump_worker_environ(9100, 2, base={"PATH": "/usr/bin"})
        self.assertEqual(env["REDPOOL_METRICS_PORT"], "9102")
        self.assertEqual(env["PATH"], "/usr/bin")


if __name__ == "__main__":
    unittest.main()
