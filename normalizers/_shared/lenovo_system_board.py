# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo marketing strings: strip trailing `` System Board`` noise.

XCC often appends `` System Board`` to product names on Chassis OEM
``ProductName`` and sometimes on ComputerSystem ``Model``. Remove it with a
case-insensitive regex so spacing variants still match.
"""

from __future__ import annotations

import re
from typing import Any

_LENOVO_SYSTEM_BOARD_SUFFIX_RE = re.compile(r"(?i)\s+system\s+board\s*$")


def strip_lenovo_system_board_suffix(value: Any) -> Any:
    """Drop trailing `` System Board`` / `` system board`` from *value* if it is a string."""
    if not isinstance(value, str):
        return value
    s = value.rstrip()
    out = _LENOVO_SYSTEM_BOARD_SUFFIX_RE.sub("", s).rstrip()
    return out if out else s
