# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""The capture tool reads the BMC password from the environment or a prompt."""

import io
import subprocess
import sys
import unittest
from unittest import mock


from redfish_snapshot.credentials import PASSWORD_ENV_VAR, PasswordError, read_password
from redfish_snapshot.main import build_parser


class TestReadPassword(unittest.TestCase):
    def test_env_var_wins_and_prompt_is_not_used(self) -> None:
        prompt = mock.Mock()
        value = read_password(
            {PASSWORD_ENV_VAR: "from-env"}, prompt=prompt, is_tty=lambda: True
        )
        self.assertEqual(value, "from-env")
        prompt.assert_not_called()

    def test_empty_env_var_counts_as_unset(self) -> None:
        prompt = mock.Mock(return_value="typed")
        value = read_password(
            {PASSWORD_ENV_VAR: ""}, prompt=prompt, is_tty=lambda: True
        )
        self.assertEqual(value, "typed")

    def test_prompts_when_stdin_is_a_terminal(self) -> None:
        prompt = mock.Mock(return_value="typed")
        self.assertEqual(read_password({}, prompt=prompt, is_tty=lambda: True), "typed")
        prompt.assert_called_once()

    def test_refuses_to_read_stdin_when_not_a_terminal(self) -> None:
        prompt = mock.Mock()
        with self.assertRaisesRegex(PasswordError, PASSWORD_ENV_VAR):
            read_password({}, prompt=prompt, is_tty=lambda: False)
        prompt.assert_not_called()

    def test_empty_prompt_answer_is_refused(self) -> None:
        with self.assertRaisesRegex(PasswordError, "empty"):
            read_password({}, prompt=lambda _: "", is_tty=lambda: True)


class TestCliHasNoPasswordFlag(unittest.TestCase):
    def test_password_flag_is_rejected(self) -> None:
        parser = build_parser()
        with mock.patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "clone",
                        "--host",
                        "h",
                        "--username",
                        "u",
                        "--password",
                        "p",
                        "--vendor",
                        "v",
                        "--model",
                        "m",
                    ]
                )

    def test_tls_warnings_flag_defaults_off(self) -> None:
        args = build_parser().parse_args(
            ["clone", "--host", "h", "--username", "u", "--vendor", "v", "--model", "m"]
        )
        self.assertFalse(args.tls_warnings)


def _insecure_warning_action(code: str) -> str:
    """Run ``code`` in a fresh interpreter; return the action the first matching filter takes.

    Filters are checked in order, so the first one that applies decides the action.
    """
    probe = (
        "import warnings, urllib3\n"
        + code
        + "\nw = urllib3.exceptions.InsecureRequestWarning\n"
        "print(next(a for a, m, c, mod, ln in warnings.filters"
        " if c and issubclass(w, c)))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


_CLIENT = (
    "from unittest import mock\n"
    "from redfish_snapshot.client import HttpClient\n"
    "with mock.patch('redfish.rest.v1.HttpClient.__init__', return_value=None):\n"
)


class TestTlsWarnings(unittest.TestCase):
    def test_default_client_hides_the_warning(self) -> None:
        self.assertEqual(
            _insecure_warning_action(
                _CLIENT + "    HttpClient(base_url='https://h')\n"
            ),
            "ignore",
        )

    def test_opt_in_shows_the_warning(self) -> None:
        self.assertEqual(
            _insecure_warning_action(
                _CLIENT
                + "    HttpClient(base_url='https://h', show_tls_warnings=True)\n"
            ),
            "default",
        )


if __name__ == "__main__":
    unittest.main()
