# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Resolve the Chassis that belongs to a ComputerSystem.

HPE serves PCIe devices, batteries and similar resources under the system's
Chassis, which is not always ``Chassis/1`` (e.g. blades). Callers with a client use
``chassis_for_system``; callers holding the ComputerSystem body use
``chassis_from_system_body``.
"""

from __future__ import annotations

import contextvars
from typing import Any, Dict, Optional, Tuple

from redpool.redfish_client import redfish_get_json

# Per-request memo; ``None`` (default) means "no memo". A resolve_backend hook
# calls ``begin_system_chassis_memo`` so the memo never outlives one request.
_memo: contextvars.ContextVar[Optional[Dict[Tuple[int, str], Optional[str]]]] = (
    contextvars.ContextVar("system_chassis_memo", default=None)
)


def begin_system_chassis_memo() -> None:
    """Start a fresh memo for the current request."""
    _memo.set({})


def chassis_from_system_body(body: Any) -> Optional[str]:
    """First ``Links.Chassis[].@odata.id`` of a ComputerSystem body, or None."""
    if not isinstance(body, dict):
        return None
    links = body.get("Links")
    chassis = links.get("Chassis") if isinstance(links, dict) else None
    if not isinstance(chassis, list):
        return None
    for item in chassis:
        if isinstance(item, dict):
            odata_id = item.get("@odata.id") or item.get("href")
            if isinstance(odata_id, str) and odata_id.strip():
                return odata_id.split("#")[0].rstrip("/")
    return None


def _get(client: Any, path: str) -> Dict[str, Any]:
    try:
        body = redfish_get_json(client, path)
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _resolve(client: Any, system_id: str) -> Optional[str]:
    found = chassis_from_system_body(_get(client, f"/redfish/v1/Systems/{system_id}"))
    if found:
        return found
    members = [
        m.get("@odata.id")
        for m in (_get(client, "/redfish/v1/Chassis").get("Members") or [])
        if isinstance(m, dict) and isinstance(m.get("@odata.id"), str)
    ]
    if len(members) == 1:
        return members[0].rstrip("/")
    return None


def chassis_for_system(client: Any, system_id: str) -> Optional[str]:
    """Chassis ``@odata.id`` for ``Systems/{system_id}``.

    Uses ``Links.Chassis``; else the only member of the Chassis collection; else None.
    """
    memo = _memo.get()
    key = (id(client), system_id)
    if memo is not None and key in memo:
        return memo[key]
    result = _resolve(client, system_id)
    if memo is not None:
        memo[key] = result
    return result
