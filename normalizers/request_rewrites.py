# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Request rewrite rules: map client request paths to backend paths and response URI rewrites.

Vendor-specific modules (e.g. normalizers/systems/pci_devices/hpe.py) register rules
so that when a client requests a canonical path (e.g. Systems/1/PCIeDevices), the proxy
can fetch a different backend path (e.g. Chassis/{id}/PCIeDevices) and rewrite all URIs in
the response so the client sees the canonical path. This keeps URL routing and rewrite
logic in the normalizer module structure instead of proxy.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from .vendor_id import canonical_server_vendor


def rewrite_response_body(
    data: Any,
    from_prefix: str,
    to_prefix: str,
) -> Any:
    """Recursively rewrite all string values: replace from_prefix with to_prefix."""
    if isinstance(data, dict):
        return {
            k: rewrite_response_body(v, from_prefix, to_prefix) for k, v in data.items()
        }
    if isinstance(data, list):
        return [rewrite_response_body(item, from_prefix, to_prefix) for item in data]
    if isinstance(data, str) and from_prefix in data:
        return data.replace(from_prefix, to_prefix)
    return data


@dataclass(frozen=True)
class RewriteCall:
    """What the proxy resolved for one rewritten request, passed to the rule hooks."""

    client: Any
    path: str
    backend_path: str
    from_prefix: str
    to_prefix: str


@dataclass(frozen=True)
class RequestRewriteRule:
    """Concrete request rewrite rule.

    Optional hooks allow vendor-specific logic without proxy knowing the vendor:
    - resolve_backend: (client, path) -> (backend_path, from_prefix, to_prefix); overrides default when present.
    - on_backend_error: (call, status) -> (body, status) or None.
    - after_200_merge: (call, body) -> body (merge/enrich before rewrite).
    - should_normalize_single: (path, backend_path) -> bool (whether to run single-resource normalizer).
    """

    vendor: str
    matches: Callable[[str], bool]
    get_backend_path: Callable[[str], str]
    get_response_rewrite: Callable[[str], Tuple[str, str]]
    resolve_backend: Optional[Callable[[Any, str], Tuple[str, str, str]]] = None
    on_backend_error: Optional[
        Callable[[RewriteCall, int], Optional[Tuple[Any, int]]]
    ] = None
    after_200_merge: Optional[Callable[[RewriteCall, Any], Any]] = None
    should_normalize_single: Optional[Callable[[str, str], bool]] = None


_rules: List[RequestRewriteRule] = []


def register_request_rewrite(rule: RequestRewriteRule) -> None:
    """Register a request rewrite rule (called from vendor modules at import time)."""
    _rules.append(rule)


def get_request_rewrite(
    vendor: str,
    path: str,
    client: Any = None,
) -> Optional[Tuple[str, str, str, RequestRewriteRule]]:
    """Return (backend_path, from_prefix, to_prefix, rule) if a rule applies, else None.

    When client is provided and the rule has resolve_backend, that is used to compute
    the backend triple; otherwise get_backend_path and get_response_rewrite are used.
    The returned rule may have optional hooks for the proxy to call (on_backend_error,
    after_200_merge, should_normalize_single) without vendor-specific code in the proxy.
    """
    if not _rules:
        # Import full chassis tree too: HPE and Lenovo Ports rules and other rules register
        # from chassis modules, not only from ``systems`` (e.g. pci_devices/hpe.py alone
        # would populate _rules and skip chassis forever).
        import importlib

        importlib.import_module("normalizers.systems")
        importlib.import_module("normalizers.chassis")
    vendor = canonical_server_vendor(vendor)
    for rule in _rules:
        if canonical_server_vendor(rule.vendor) != vendor:
            continue
        if not rule.matches(path):
            continue
        if rule.resolve_backend is not None and client is not None:
            backend_path, from_prefix, to_prefix = rule.resolve_backend(client, path)
        else:
            backend_path = rule.get_backend_path(path)
            from_prefix, to_prefix = rule.get_response_rewrite(path)
        return (backend_path, from_prefix, to_prefix, rule)
    return None
