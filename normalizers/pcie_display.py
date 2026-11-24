# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Shared helpers for PCIe device/function display fields (inventory metrics)."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from .types import NormalizationContext

_FUNCTION_PLACEHOLDER_RE = re.compile(r"^function\s+\d+\s*$", re.I)

# HPE often uses 699-xxxxx-style tokens for both Model and PartNumber while
# putting the product string on Name (e.g. GPUs).
_HPE_SKU_MODEL_RE = re.compile(r"^\d{3}-\d{5}-\d{4}-\d{3}$")


def prefer_pcie_device_product_model(
    model: Any,
    name: Any,
    part_number: Any,
) -> Optional[str]:
    """When Model duplicates the FRU token and Name is a product label, use Name.

    Returns the string to use as ``Model``, or ``None`` to keep the caller's
    default (raw ``Model`` / pci.ids fallback).
    """
    m_str = model.strip() if isinstance(model, str) else ""
    n_str = name.strip() if isinstance(name, str) else ""
    p_str = part_number.strip() if isinstance(part_number, str) else ""
    if not m_str or not n_str or m_str.casefold() == n_str.casefold():
        return None
    if _FUNCTION_PLACEHOLDER_RE.match(n_str):
        return None
    if not _HPE_SKU_MODEL_RE.match(m_str):
        return None
    if p_str and m_str != p_str:
        return None
    return n_str


def coalesce_pcie_device_model(model: Any, name: Any, description: Any) -> Any:
    """Prefer non-empty ``Model``; otherwise ``Name`` or ``Description`` (e.g. Dell null Model)."""
    if isinstance(model, str) and model.strip():
        return model.strip()
    if isinstance(model, (int, float)):
        return str(model)
    if model not in (None, ""):
        return model
    if isinstance(name, str) and name.strip():
        return name.strip()
    if isinstance(description, str) and description.strip():
        return description.strip()
    return model


PARENT_PCIE_DEVICE_PREFETCH_KEY = "parent_pcie_device"


def _parent_pcie_device_candidates(odata_id: str, client: Any = None) -> list[str]:
    """URL(s) to try for the parent device of a ``…/PCIeFunctions/{id}`` resource.

    With a client the system's Chassis is resolved; Chassis/1 is used only when no
    client is available or the system has no resolvable Chassis.
    """
    marker = "/PCIeFunctions/"
    if marker not in odata_id:
        return []
    parent = odata_id.split(marker, 1)[0].split("#", 1)[0]
    if not parent.startswith("/"):
        return []
    out = [parent]
    # HPE (and some mocks) expose PCIe devices under the system's Chassis while the
    # client requests Systems/{id}/PCIeDevices/… after proxy URI rewrite.
    if "/Systems/" in parent and "/PCIeDevices/" in parent:
        chassis = None
        m = re.match(r"/redfish/v1/Systems/([^/]+)", parent)
        if client is not None and m:
            from ._shared.system_chassis import chassis_for_system

            chassis = chassis_for_system(client, m.group(1))
        target = chassis or "/redfish/v1/Chassis/1"
        out.append(
            re.sub(
                r"/redfish/v1/Systems/[^/]+",
                lambda _m: target,
                parent,
                count=1,
            )
        )
    return out


def prefetch_parent_pcie_device_for_function(ctx: NormalizationContext) -> None:
    """Load parent ``PCIeDevice`` JSON for ``…/PCIeDevices/{id}/PCIeFunctions/…`` paths."""
    ctx.prefetched.pop(PARENT_PCIE_DEVICE_PREFETCH_KEY, None)
    if getattr(ctx, "client", None) is None:
        return
    oid = (getattr(ctx, "odata_id", None) or "").split("#", 1)[0]
    if "/PCIeFunctions/" not in oid:
        return
    try:
        from redpool.redfish_client import redfish_get_json

        for parent_path in _parent_pcie_device_candidates(oid, ctx.client):
            body = redfish_get_json(ctx.client, parent_path)
            if not isinstance(body, dict):
                continue
            name = body.get("Name")
            if isinstance(name, str) and name.strip():
                ctx.prefetched[PARENT_PCIE_DEVICE_PREFETCH_KEY] = body
                return
    except Exception:
        return


def pcie_function_display_name(
    ctx: NormalizationContext,
    strip_bdf_suffix: Callable[[Any], Any],
) -> Any:
    """Use parent device ``Name`` when the function name is only ``Function {n}``."""
    raw_name = ctx.data.get("Name")
    name = strip_bdf_suffix(raw_name)
    if not isinstance(name, str) or not _FUNCTION_PLACEHOLDER_RE.match(name.strip()):
        return name
    dev = ctx.prefetched.get(PARENT_PCIE_DEVICE_PREFETCH_KEY)
    if not isinstance(dev, dict):
        return name
    dn = strip_bdf_suffix(dev.get("Name"))
    if isinstance(dn, str) and dn.strip():
        return dn.strip()
    return name
