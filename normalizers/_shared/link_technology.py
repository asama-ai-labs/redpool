# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Link technology implied by a port's address format.

A 48-bit MAC address is Ethernet addressing. Fibre Channel ports use 64-bit WWNs and
InfiniBand uses 20-byte GUIDs, so a MAC-format address identifies the technology.
"""

from __future__ import annotations

import re
from typing import Any, Optional

_MAC48 = re.compile(
    r"^[0-9A-Fa-f]{2}(?P<sep>[:-]?)(?:[0-9A-Fa-f]{2}(?P=sep)){4}[0-9A-Fa-f]{2}$"
)


def ethernet_from_mac_address(value: Any) -> Optional[str]:
    """``"Ethernet"`` when *value* is a 48-bit MAC address; None otherwise."""
    if not isinstance(value, str):
        return None
    return "Ethernet" if _MAC48.match(value.strip()) else None
