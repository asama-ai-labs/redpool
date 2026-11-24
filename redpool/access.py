# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Which targets and paths a caller may ask Redpool to fetch.

Redpool turns ``http(s)://host:port/path`` into a backend fetch. This module
decides, before any backend call, whether the host is on the operator's
allowlist and whether the path is a Redfish path. It has no mitmproxy
dependency so it can be tested on its own.
"""

from __future__ import annotations

import ipaddress
import posixpath
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Iterable, List, Optional, Union
from urllib.parse import unquote

_IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


def parse_target_list(value: Union[str, Iterable[str], None]) -> List[str]:
    """Normalize a comma-separated string or a list into a list of entries."""
    if value is None:
        return []
    items = value.split(",") if isinstance(value, str) else list(value)
    return [str(i).strip() for i in items if str(i).strip()]


def _strip_brackets(host: str) -> str:
    return host[1:-1] if host.startswith("[") and host.endswith("]") else host


def _as_ip(host: str) -> Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
    try:
        return ipaddress.ip_address(_strip_brackets(host).split("%", 1)[0])
    except ValueError:
        return None


def is_redfish_path(path: str) -> bool:
    """True for ``/redfish`` and anything below it, after decoding and normalizing."""
    # Decode twice so ``%252e%252e`` cannot hide a ``..`` from the normalizer.
    decoded = unquote(unquote(path.split("?", 1)[0]))
    if not decoded.startswith("/"):
        return False
    normalized = posixpath.normpath(decoded)
    # normpath keeps a leading "//" as is; treat it as not a Redfish path.
    if normalized.startswith("//"):
        return False
    return normalized == "/redfish" or normalized.startswith("/redfish/")


# A glob made only of digits, dots and wildcards (``10.1.*``) reads as an IP range but is
# matched against host names, so it would let ``10.1.attacker.com`` through.
_IP_SHAPED_GLOB = re.compile(r"[0-9.*?\[\]-]+")


def _reject_ip_shaped_name(entry: str, name: str) -> None:
    """Refuse allowlist entries that look like IPs or CIDRs but are not valid ones."""
    if (
        "/" in name
        or ":" in name
        or (any(c in name for c in "*?[") and _IP_SHAPED_GLOB.fullmatch(name))
    ):
        raise ValueError(
            f"allowed_targets entry {entry!r} looks like an IP address or range but "
            "is not a valid one. Use a CIDR such as 10.1.0.0/16 for an address range; "
            "globs match host names only."
        )


@dataclass
class TargetPolicy:
    """Allowlist of hosts plus an optional ``/redfish``-only path rule.

    An empty allowlist allows every host. A CIDR entry matches only a request
    that names an IP address. A hostname is never resolved, so a name cannot
    be matched against a CIDR (and DNS cannot be used to dodge the list).
    """

    allowed_targets: List[str] = field(default_factory=list)
    require_redfish_path: bool = True

    def __post_init__(self) -> None:
        self._networks: List[_IPNetwork] = []
        self._names: List[str] = []
        for entry in parse_target_list(self.allowed_targets):
            try:
                self._networks.append(ipaddress.ip_network(entry, strict=False))
                continue
            except ValueError:
                pass
            name = _strip_brackets(entry).lower()
            _reject_ip_shaped_name(entry, name)
            self._names.append(name)

    def host_allowed(self, hostname: Optional[str]) -> bool:
        if not self._networks and not self._names:
            return True
        if not hostname:
            return False
        host = _strip_brackets(hostname).lower()
        ip = _as_ip(host)
        if ip is not None:
            if any(ip in net for net in self._networks if net.version == ip.version):
                return True
            # A bare IP in the list is parsed as a /32 network above.
            return False
        return any(fnmatchcase(host, pattern) for pattern in self._names)

    def check_path(self, path: str) -> Optional[str]:
        if self.require_redfish_path and not is_redfish_path(path):
            return "only /redfish paths are served"
        return None

    def check(self, hostname: Optional[str], path: str) -> Optional[str]:
        """Return a reason the request must be refused, or ``None`` to allow it."""
        if not self.host_allowed(hostname):
            return "target host is not on the allowlist"
        return self.check_path(path)
