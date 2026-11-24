# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell-specific Volume normalizer (OEM strip size)."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ....types import NormalizationContext
from .base import BaseVolumeNormalizer

# Dell reports stripe width as strings like ``64KB`` on ``Oem.Dell`` rather than top-level
# ``StripSizeBytes`` (gofish then exposes 0). Match Redfish ``OptimumIOSizeBytes`` where present.
_STRIPE_BYTES_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|KiB|MiB|GiB)\s*$",
    re.IGNORECASE,
)


def _parse_dell_stripe_size_to_bytes(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float):
        i = int(value)
        return i if i > 0 else None
    if not isinstance(value, str):
        return None
    m = _STRIPE_BYTES_RE.match(value.strip())
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2).lower()
    mult = {
        "b": 1,
        "kb": 1024,
        "mb": 1024**2,
        "gb": 1024**3,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
    }.get(unit)
    if mult is None:
        return None
    out = int(num * mult)
    return out if out > 0 else None


def _dell_oem_stripe_size_bytes(ctx: NormalizationContext) -> Optional[int]:
    oem = ctx.data.get("Oem")
    if not isinstance(oem, dict):
        return None
    dell = oem.get("Dell")
    if not isinstance(dell, dict):
        return None
    stripe: Any = None
    vd = dell.get("DellVirtualDisk")
    if isinstance(vd, dict):
        stripe = vd.get("StripeSize")
    if stripe is None:
        dv = dell.get("DellVolume")
        if isinstance(dv, dict):
            stripe = dv.get("StripeSize")
    return _parse_dell_stripe_size_to_bytes(stripe)


_SMASHED_APPLY_TIME = "@Redfish.OperationApplyTime@Redfish.AllowableValues"


def _dell_volume_actions(ctx: NormalizationContext) -> Any:
    """Drop the pre-Settings annotation Dell duplicates next to OperationApplyTimeSupport."""
    actions = ctx.data.get("Actions")
    if not isinstance(actions, dict):
        return actions if actions is not None else {}
    out: Dict[str, Any] = {}
    for key, value in actions.items():
        if isinstance(value, dict) and _SMASHED_APPLY_TIME in value:
            value = {
                item_key: item
                for item_key, item in value.items()
                if item_key != _SMASHED_APPLY_TIME
            }
        out[key] = value
    return out


def _volume_strip_size_bytes(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("StripSizeBytes")
    if isinstance(raw, int) and raw > 0:
        return raw
    if isinstance(raw, float) and raw > 0:
        return int(raw)
    oem_bytes = _dell_oem_stripe_size_bytes(ctx)
    if oem_bytes is not None:
        return oem_bytes
    return raw


class DellVolumeNormalizer(BaseVolumeNormalizer):
    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["StripSizeBytes"] = _volume_strip_size_bytes
        m["Actions"] = _dell_volume_actions
        return m
