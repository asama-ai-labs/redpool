# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Registry for vendor-specific ComputerSystem response expanders.

After normalizing a response, the proxy calls the vendor's expander if one is registered.
Expanders decide themselves whether the response applies (e.g. single System with
PCIeDevices). This keeps all system/PCIe-specific logic in the normalizer layer.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .vendor_id import canonical_server_vendor

_expanders: Dict[str, Callable[..., Dict[str, Any]]] = {}


def register_system_response_expander(
    vendor: str, expander: Callable[..., Dict[str, Any]]
) -> None:
    """Register an expander for the given vendor (e.g. 'HPE').

    The expander will be called with:
      (data, path, client, *, proxy_request=None, backend_client=None, server_metadata=None)
    and must return the (possibly modified) data dict. It may no-op when the response does not apply.
    """
    _expanders[canonical_server_vendor(vendor)] = expander


def get_system_response_expander(
    vendor: str,
) -> Optional[Callable[..., Dict[str, Any]]]:
    """Return the registered expander for the vendor, or None."""
    if not _expanders and vendor:
        from normalizers import systems  # noqa: F401  # trigger HPE registration
    return _expanders.get(canonical_server_vendor(vendor))
