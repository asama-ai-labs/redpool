# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""/metrics binds loopback by default, and DEBUG does not print credential headers."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from redpool import config, metrics
from redpool.config import RedpoolConfig, mitmproxy_option_updates

REPO_YAML = Path(__file__).resolve().parent.parent / "redpool.yaml"


class TestMetricsHostSetting(unittest.TestCase):
    def test_default_is_loopback(self) -> None:
        with patch.dict(os.environ, {"REDPOOL_CONFIG": "/nonexistent/redpool.yaml"}):
            os.environ.pop("REDPOOL_METRICS_HOST", None)
            self.assertEqual(RedpoolConfig().metrics_host, "127.0.0.1")

    def test_yaml_setting_is_used(self) -> None:
        with patch.dict(os.environ, {"REDPOOL_CONFIG": "/nonexistent/redpool.yaml"}):
            os.environ.pop("REDPOOL_METRICS_HOST", None)
            cfg = RedpoolConfig(overrides={"proxy": {"metrics_host": "10.0.0.5"}})
            self.assertEqual(cfg.metrics_host, "10.0.0.5")

    def test_environment_overrides_yaml(self) -> None:
        with patch.dict(
            os.environ,
            {
                "REDPOOL_CONFIG": "/nonexistent/redpool.yaml",
                "REDPOOL_METRICS_HOST": "0.0.0.0",
            },
        ):
            cfg = RedpoolConfig(overrides={"proxy": {"metrics_host": "10.0.0.5"}})
            self.assertEqual(cfg.metrics_host, "0.0.0.0")

    def test_blank_values_fall_back_to_loopback(self) -> None:
        with patch.dict(
            os.environ,
            {
                "REDPOOL_CONFIG": "/nonexistent/redpool.yaml",
                "REDPOOL_METRICS_HOST": "  ",
            },
        ):
            cfg = RedpoolConfig(overrides={"proxy": {"metrics_host": ""}})
            self.assertEqual(cfg.metrics_host, "127.0.0.1")

    def test_repo_yaml_matches_the_built_in_default(self) -> None:
        shipped = config._load_yaml(REPO_YAML)["proxy"]["metrics_host"]
        self.assertEqual(shipped, config._DEFAULTS["proxy"]["metrics_host"])


class TestStartMetricsServer(unittest.TestCase):
    def test_binds_the_given_address(self) -> None:
        with patch("redpool.metrics.start_http_server") as start:
            metrics.start_metrics_server(9101, "127.0.0.1")
        start.assert_called_once_with(9101, addr="127.0.0.1")

    def test_loopback_addresses_do_not_warn(self) -> None:
        for host in ("127.0.0.1", "::1", "localhost"):
            with self.subTest(host=host):
                with patch("redpool.metrics.start_http_server"):
                    with self.assertLogs("redpool.metrics", level="INFO") as logs:
                        metrics.start_metrics_server(9101, host)
                self.assertTrue(all(r.levelname == "INFO" for r in logs.records))

    def test_other_addresses_warn(self) -> None:
        for host in ("0.0.0.0", "10.0.0.5", "metrics.example.net"):
            with self.subTest(host=host):
                with patch("redpool.metrics.start_http_server"):
                    with self.assertLogs("redpool.metrics", level="INFO") as logs:
                        metrics.start_metrics_server(9101, host)
                self.assertEqual([r.levelname for r in logs.records], ["WARNING"])
                self.assertIn("not authenticated", logs.output[0])


class TestDebugFlowDetail(unittest.TestCase):
    def _options(self, level: str) -> dict:
        with patch.object(
            config, "cfg", RedpoolConfig(overrides={"proxy": {"log_level": level}})
        ):
            return mitmproxy_option_updates()

    def test_debug_does_not_print_headers(self) -> None:
        opts = self._options("DEBUG")
        self.assertEqual(opts["termlog_verbosity"], "debug")
        # mitmproxy flow_detail 2 and above print request headers, credentials included.
        self.assertLessEqual(opts["flow_detail"], 1)

    def test_quieter_levels_print_no_flows(self) -> None:
        for level in ("WARNING", "ERROR", "CRITICAL"):
            with self.subTest(level=level):
                self.assertEqual(self._options(level)["flow_detail"], 0)


if __name__ == "__main__":
    unittest.main()
