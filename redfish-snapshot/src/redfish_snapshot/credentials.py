# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Where the capture tool gets the BMC password.

The password is never a command-line argument, because arguments show up in
shell history and in ``ps``. It comes from the ``REDFISH_SNAPSHOT_PASSWORD``
environment variable, or from an interactive prompt when stdin is a terminal.
"""

from __future__ import annotations

import getpass
import os
import sys
from typing import Callable, Mapping, Optional

PASSWORD_ENV_VAR = "REDFISH_SNAPSHOT_PASSWORD"


class PasswordError(RuntimeError):
    """No usable password could be read."""


def read_password(
    environ: Optional[Mapping[str, str]] = None,
    prompt: Callable[[str], str] = getpass.getpass,
    is_tty: Optional[Callable[[], bool]] = None,
) -> str:
    """Return the password from the environment, else from a prompt.

    An empty environment variable counts as unset. Without a terminal and
    without the variable, this raises rather than waiting on stdin.
    """
    env = os.environ if environ is None else environ
    value = env.get(PASSWORD_ENV_VAR, "")
    if value:
        return value
    tty = sys.stdin.isatty if is_tty is None else is_tty
    if not tty():
        raise PasswordError(
            f"no password: set {PASSWORD_ENV_VAR} or run from a terminal to be prompted"
        )
    value = prompt("BMC password: ")
    if not value:
        raise PasswordError("empty password")
    return value
