# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""BMC TLS verification is off by default and opt-in through proxy.tls_verify."""

import unittest
from unittest import mock

import requests.certs

from redpool.config import RedpoolConfig, bmc_tls_cafile
from redpool.proxy import RedfishProxy


def _cfg(proxy: dict) -> RedpoolConfig:
    return RedpoolConfig({"proxy": proxy})


class TestTlsConfig(unittest.TestCase):
    def test_default_is_off_and_passes_no_cafile(self) -> None:
        c = _cfg({})
        self.assertFalse(c.tls_verify)
        self.assertEqual(c.ca_file, "")

    def test_on_with_ca_file_uses_it(self) -> None:
        with mock.patch(
            "redpool.config.cfg", _cfg({"tls_verify": True, "ca_file": "/x/ca.pem"})
        ):
            self.assertEqual(bmc_tls_cafile(), "/x/ca.pem")

    def test_on_without_ca_file_uses_the_system_bundle(self) -> None:
        with mock.patch("redpool.config.cfg", _cfg({"tls_verify": True})):
            self.assertEqual(bmc_tls_cafile(), requests.certs.where())

    def test_off_passes_none_even_with_a_ca_file(self) -> None:
        with mock.patch("redpool.config.cfg", _cfg({"ca_file": "/x/ca.pem"})):
            self.assertIsNone(bmc_tls_cafile())


class TestClientCreation(unittest.TestCase):
    def _create(self, proxy_cfg: dict) -> dict:
        proxy = RedfishProxy(max_targets=5)
        with (
            mock.patch("redpool.config.cfg", _cfg(proxy_cfg)),
            mock.patch("redpool.proxy.cfg", _cfg(proxy_cfg)),
            mock.patch("redpool.proxy.redfish.redfish_client") as factory,
            mock.patch("redpool.proxy.limit_session_to_one_connection"),
            mock.patch("redpool.proxy.CachedRedfishClient"),
        ):
            try:
                proxy._create_client("https://bmc.example", "u", "p", None, "anon")
            except Exception:
                pass
        return factory.call_args.kwargs

    def test_default_client_gets_no_cafile(self) -> None:
        self.assertIsNone(self._create({}).get("cafile"))

    def test_verified_client_gets_the_ca_file(self) -> None:
        kwargs = self._create({"tls_verify": True, "ca_file": __file__})
        self.assertEqual(kwargs["cafile"], __file__)


class TestStartup(unittest.TestCase):
    def test_missing_ca_file_fails_fast(self) -> None:
        with mock.patch(
            "redpool.proxy.cfg", _cfg({"tls_verify": True, "ca_file": "/no/such.pem"})
        ):
            with self.assertRaisesRegex(ValueError, "does not exist"):
                RedfishProxy(max_targets=5)

    def test_off_logs_a_warning(self) -> None:
        with (
            mock.patch("redpool.proxy.cfg", _cfg({})),
            self.assertLogs("redpool.proxy", level="WARNING") as logs,
        ):
            RedfishProxy(max_targets=5)
        self.assertTrue(any("NOT verified" in m for m in logs.output))

    def test_on_does_not_warn(self) -> None:
        with mock.patch("redpool.proxy.cfg", _cfg({"tls_verify": True})):
            proxy = RedfishProxy(max_targets=5)
        self.assertIsNotNone(proxy)


if __name__ == "__main__":
    unittest.main()
