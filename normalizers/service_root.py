# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Which ``ServiceRoot.Product`` strings name the BMC rather than the platform.

Some BMCs publish their own name as ``Product``, a string every server of that vendor shares,
so it cannot pick a model-specific table. The proxy asks :func:`product_names_bmc` and does
not know any vendor. A vendor module registers its marker with
:func:`register_bmc_product_marker` when it is imported.
"""

from __future__ import annotations

_BMC_PRODUCT_MARKERS: list[str] = []


def register_bmc_product_marker(marker: str) -> None:
    """Treat a ``Product`` containing *marker* (any letter case) as the BMC's name."""
    m = marker.strip().lower()
    if m and m not in _BMC_PRODUCT_MARKERS:
        _BMC_PRODUCT_MARKERS.append(m)


def product_names_bmc(product: str) -> bool:
    """True when *product* contains a registered marker."""
    p = (product or "").strip().lower()
    return any(marker in p for marker in _BMC_PRODUCT_MARKERS)
