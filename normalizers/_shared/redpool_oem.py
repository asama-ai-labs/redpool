# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Copy a numeric vendor field into ``Oem.Redpool``."""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from ..types import NormalizationContext


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def numeric_oem_value(data: Dict[str, Any], key: str) -> Optional[float | int]:
    """Return a top-level number, else the first vendor OEM number for ``key``."""
    top = data.get(key)
    if _is_number(top):
        return top
    oem = data.get("Oem")
    if not isinstance(oem, dict):
        return None
    redpool = oem.get("Redpool")
    if isinstance(redpool, dict) and _is_number(redpool.get(key)):
        return redpool[key]
    for name, block in oem.items():
        if name == "Redpool" or not isinstance(block, dict):
            continue
        value = block.get(key)
        if _is_number(value):
            return value
    return None


def oem_with_numeric_redpool(ctx: NormalizationContext, key: str) -> Dict[str, Any]:
    """Preserve vendor ``Oem`` and set ``Oem.Redpool.<key>`` when a number exists."""
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    value = numeric_oem_value(ctx.data, key)
    if value is None:
        return out
    redpool = out.get("Redpool")
    merged: Dict[str, Any] = dict(redpool) if isinstance(redpool, dict) else {}
    merged[key] = value
    out["Redpool"] = merged
    return out


# The published OEM schema is Redpool.v1_0_0. Each Oem.Redpool object names the
# definition for its owning resource, for example #Redpool.v1_0_0.RedpoolChassis.
REDPOOL_OEM_NAMESPACE = "Redpool.v1_0_0"
# Legacy PowerSupplies members carry no @odata.type; their parent key names them.
_UNTYPED_OWNER_BY_PARENT_KEY = {"PowerSupplies": "PowerSupply"}


def _owner_name(obj: Dict[str, Any], parent_key: str) -> Optional[str]:
    """Resource name that owns *obj*: the first segment of its @odata.type, or its parent's."""
    odata_type = obj.get("@odata.type")
    if isinstance(odata_type, str) and odata_type.strip():
        return odata_type.strip().lstrip("#").split(".")[0] or None
    return _UNTYPED_OWNER_BY_PARENT_KEY.get(parent_key)


def stamp_redpool_oem_types(body: Any, parent_key: str = "") -> Any:
    """Set ``@odata.type`` on every ``Oem.Redpool`` object in *body*, in place.

    The type names the published definition for the owning resource, so each block
    is validated against the schema it belongs to. This is generic: it reads only
    the document's own type names, never a vendor.
    """
    if isinstance(body, list):
        for item in body:
            stamp_redpool_oem_types(item, parent_key)
        return body
    if not isinstance(body, dict):
        return body
    oem = body.get("Oem")
    if isinstance(oem, dict) and isinstance(oem.get("Redpool"), dict):
        owner = _owner_name(body, parent_key)
        if owner:
            oem["Redpool"]["@odata.type"] = f"#{REDPOOL_OEM_NAMESPACE}.Redpool{owner}"
    for key, value in body.items():
        stamp_redpool_oem_types(value, key)
    return body
