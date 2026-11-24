# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell's ``DellNetworkAttributes.Attributes.LinkStatus`` mapped to Redfish ``LinkStatus``."""

from __future__ import annotations

from typing import Any, Optional


def canonicalize_dell_oem_link_status(value: Any) -> Optional[str]:
    """Map Dell ``DellNetworkAttributes.Attributes.LinkStatus`` to Redfish ``LinkStatus``."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ("connected", "linkup", "up"):
        return "LinkUp"
    if v in ("disconnected", "linkdown", "down"):
        return "LinkDown"
    if v in ("no link", "no_link", "nolink"):
        return "NoLink"
    return None
