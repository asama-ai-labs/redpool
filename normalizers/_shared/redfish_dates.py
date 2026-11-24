# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Redfish date-time values.

Some BMCs send an all-zero placeholder (``0000-00-00T00:00:00Z``) for a time they
do not know. A date-time property must hold a real date-time or null, so the
placeholder becomes null and the property is omitted from sparse bodies.
"""

from __future__ import annotations

from typing import Any, Optional


def date_time_or_none(value: Any) -> Optional[str]:
    """Return *value* when it is a real date-time string; None for placeholders or non-strings."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or s.startswith("0000-"):
        return None
    return s
