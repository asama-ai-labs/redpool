# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Allowlist and path rules for who a caller may make Redpool fetch."""

import os
import unittest
from unittest import mock

from redpool.access import TargetPolicy, is_redfish_path, parse_target_list
from redpool.config import ConfigError, RedpoolConfig


class TestHostAllowlist(unittest.TestCase):
    def test_empty_list_allows_any_host(self) -> None:
        self.assertIsNone(TargetPolicy().check("anything.example", "/redfish/v1/"))

    def test_exact_name_is_case_insensitive(self) -> None:
        p = TargetPolicy(["BMC01.corp.example"])
        self.assertIsNone(p.check("bmc01.CORP.example", "/redfish/v1/"))
        self.assertIsNotNone(p.check("bmc02.corp.example", "/redfish/v1/"))

    def test_glob(self) -> None:
        p = TargetPolicy(["*.bmc.example"])
        self.assertIsNone(p.check("a.bmc.example", "/redfish/v1/"))
        self.assertIsNotNone(p.check("a.bmc.example.evil.net", "/redfish/v1/"))
        self.assertIsNotNone(p.check("bmc.example", "/redfish/v1/"))

    def test_cidr_v4_and_bare_ip(self) -> None:
        p = TargetPolicy(["10.20.0.0/16", "192.0.2.7"])
        self.assertIsNone(p.check("10.20.5.9", "/redfish/v1/"))
        self.assertIsNone(p.check("192.0.2.7", "/redfish/v1/"))
        self.assertIsNotNone(p.check("10.21.0.1", "/redfish/v1/"))
        self.assertIsNotNone(p.check("192.0.2.8", "/redfish/v1/"))

    def test_cidr_v6(self) -> None:
        p = TargetPolicy(["2001:db8::/32"])
        self.assertIsNone(p.check("2001:db8::5", "/redfish/v1/"))
        self.assertIsNone(p.check("[2001:db8::5]", "/redfish/v1/"))
        self.assertIsNotNone(p.check("2001:db9::5", "/redfish/v1/"))
        self.assertIsNotNone(p.check("10.0.0.1", "/redfish/v1/"))

    def test_name_is_never_matched_against_a_cidr(self) -> None:
        p = TargetPolicy(["10.0.0.0/8"])
        self.assertIsNotNone(p.check("localhost", "/redfish/v1/"))
        self.assertIsNotNone(p.check("10.0.0.1.evil.net", "/redfish/v1/"))

    def test_missing_host_is_refused_when_a_list_is_set(self) -> None:
        self.assertIsNotNone(TargetPolicy(["a.example"]).check(None, "/redfish/v1/"))


class TestPathRule(unittest.TestCase):
    def test_redfish_paths(self) -> None:
        for path in (
            "/redfish",
            "/redfish/",
            "/redfish/v1",
            "/redfish/v1/Systems/1?$expand=.",
            "/redfish/v1/$metadata",
        ):
            self.assertTrue(is_redfish_path(path), path)

    def test_other_paths_and_traversal(self) -> None:
        for path in (
            "/",
            "/etc/passwd",
            "/redfishx/v1",
            "/redfish/../etc/passwd",
            "/redfish/%2e%2e/etc/passwd",
            "/redfish/%252e%252e/etc",
            "//redfish/v1",
            "redfish/v1",
        ):
            self.assertFalse(is_redfish_path(path), path)

    def test_rule_can_be_turned_off(self) -> None:
        p = TargetPolicy(require_redfish_path=False)
        self.assertIsNone(p.check("a.example", "/ui"))
        self.assertIsNotNone(TargetPolicy().check("a.example", "/ui"))

    def test_check_path_ignores_the_host_list(self) -> None:
        p = TargetPolicy(["a.example"])
        self.assertIsNone(p.check_path("/redfish/v1/"))
        self.assertIsNotNone(p.check_path("/x"))


class TestConfig(unittest.TestCase):
    def test_parse_target_list(self) -> None:
        self.assertEqual(parse_target_list(" a , b,, "), ["a", "b"])
        self.assertEqual(parse_target_list(["a", " b "]), ["a", "b"])
        self.assertEqual(parse_target_list(None), [])

    def test_env_overrides_yaml_list(self) -> None:
        c = RedpoolConfig({"proxy": {"allowed_targets": ["yaml.example"]}})
        with mock.patch.dict(
            os.environ, {"REDPOOL_ALLOWED_TARGETS": "a.example, 10.0.0.0/8"}
        ):
            self.assertEqual(c.allowed_targets, ["a.example", "10.0.0.0/8"])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDPOOL_ALLOWED_TARGETS", None)
            self.assertEqual(c.allowed_targets, ["yaml.example"])

    def test_defaults(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REDPOOL_ALLOWED_TARGETS", None)
            c = RedpoolConfig({})
            self.assertEqual(c.allowed_targets, [])
            self.assertTrue(c.require_redfish_path)
            self.assertEqual(c.max_targets, 2048)


if __name__ == "__main__":
    unittest.main()


class TestStrictAllowlist(unittest.TestCase):
    def test_ip_shaped_globs_are_refused(self) -> None:
        for entry in (
            "10.1.*",
            "10.*.*.*",
            "192.168.?.1",
            "10.1.0.0/33",
            "2001:db8::*",
        ):
            with self.subTest(entry=entry):
                with self.assertRaises(ValueError) as ctx:
                    TargetPolicy([entry])
                self.assertIn("CIDR", str(ctx.exception))

    def test_name_globs_and_cidrs_still_load(self) -> None:
        TargetPolicy(
            ["*.bmc.example", "bmc-10.*.example", "10.1.0.0/16", "2001:db8::1"]
        )


class TestConfigFailsClosed(unittest.TestCase):
    def _load(self, text: str) -> RedpoolConfig:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write(text)
        try:
            with mock.patch.dict(os.environ, {"REDPOOL_CONFIG": fh.name}):
                return RedpoolConfig()
        finally:
            os.unlink(fh.name)

    def test_unparseable_yaml_is_an_error(self) -> None:
        with self.assertRaises(ConfigError):
            self._load("proxy:\n  allowed_targets: [10.0.0.1\n")

    def test_unknown_key_is_an_error_and_names_it(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._load("proxy:\n  allowed_target: [10.0.0.1]\n")
        self.assertIn("proxy.allowed_target", str(ctx.exception))

    def test_unknown_section_is_an_error(self) -> None:
        with self.assertRaises(ConfigError):
            self._load("prxy:\n  log_level: DEBUG\n")

    def test_non_mapping_file_is_an_error(self) -> None:
        with self.assertRaises(ConfigError):
            self._load("- just\n- a list\n")

    def test_valid_and_empty_files_load(self) -> None:
        self.assertEqual(
            self._load("proxy:\n  allowed_targets: [10.0.0.0/8]\n").allowed_targets,
            ["10.0.0.0/8"],
        )
        self.assertEqual(self._load("").allowed_targets, [])
        self.assertEqual(self._load("# only a comment\n").allowed_targets, [])
