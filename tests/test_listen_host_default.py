# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Redpool listens on loopback unless the operator says otherwise."""

import unittest
from unittest import mock

from redpool import __main__ as entry
from redpool.shard_supervisor import build_arg_parser


class TestListenHostDefault(unittest.TestCase):
    def test_spellings_that_set_listen_host(self) -> None:
        for argv in (
            ["--listen-host", "0.0.0.0"],
            ["--listen-host=0.0.0.0"],
            ["--set", "listen_host=0.0.0.0"],
            ["--set=listen_host=0.0.0.0"],
            ["-p", "7000", "@0.0.0.0:7000"],
        ):
            self.assertTrue(entry._has_listen_host(argv), argv)

    def test_other_arguments_do_not(self) -> None:
        for argv in (
            [],
            ["-p", "7000", "-k"],
            ["--set", "listen_port=7000"],
            ["--set", "connection_strategy=lazy"],
        ):
            self.assertFalse(entry._has_listen_host(argv), argv)

    def _run(self, argv: list[str]) -> list[str]:
        proc = mock.Mock()
        proc.wait.return_value = 0
        with (
            mock.patch.object(entry.sys, "argv", ["redpool-proxy", *argv]),
            mock.patch.object(entry.subprocess, "Popen", return_value=proc) as popen,
        ):
            entry.main()
        return popen.call_args[0][0]

    def test_default_is_injected(self) -> None:
        cmd = self._run(["-p", "7000", "-k"])
        i = cmd.index("--listen-host")
        self.assertEqual(cmd[i + 1], "127.0.0.1")

    def test_explicit_value_is_kept(self) -> None:
        cmd = self._run(["--listen-host", "0.0.0.0", "-p", "7000"])
        self.assertEqual(cmd.count("--listen-host"), 1)
        self.assertEqual(cmd[cmd.index("--listen-host") + 1], "0.0.0.0")

    def test_shard_front_and_admin_default_to_loopback(self) -> None:
        args = build_arg_parser().parse_args([])
        self.assertEqual(args.front_host, "127.0.0.1")
        self.assertEqual(args.parent_admin_host, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
