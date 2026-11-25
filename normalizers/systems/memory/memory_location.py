# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""``MemoryLocation`` generation shared by the Memory normalizers.

The generic path passes a complete BMC ``MemoryLocation`` (all four fields integers)
through unchanged and preserves partial integers. Vendor behavior lives in the vendor's
registered Memory normalizer, which supplies ``canonical`` (rewrite a complete quadruple)
or ``locator`` (fill gaps). Vendors without such a normalizer get the generic passthrough.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional, Tuple

from ...types import NormalizationContext

MEM_KEYS = ("Socket", "MemoryController", "Channel", "Slot")

_MemoryLocationQuad = Tuple[int, int, int, int]


def as_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def model_fold(model: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (model or "").lower())


def dec1(v: int) -> int:
    """Map 1-based BMC integer to 0-based; leave 0 unchanged."""
    return v - 1 if v >= 1 else v


def generate_memory_location(
    ctx: NormalizationContext,
    *,
    canonical: Optional[
        Callable[[NormalizationContext, _MemoryLocationQuad], _MemoryLocationQuad]
    ] = None,
    locator: Optional[
        Callable[[NormalizationContext], Optional[Tuple[int, Optional[int], int, int]]]
    ] = None,
) -> Any:
    """Normalize or assemble ``MemoryLocation`` on ``ctx.data``.

    ``canonical`` rewrites a complete BMC quadruple; ``locator`` supplies coordinates for
    incomplete payloads. Both are provided by vendor normalizers.
    """
    raw = ctx.data.get("MemoryLocation")

    base: Dict[str, Optional[int]] = {
        "Socket": None,
        "MemoryController": None,
        "Channel": None,
        "Slot": None,
    }
    if isinstance(raw, dict):
        for k in MEM_KEYS:
            base[k] = as_int(raw.get(k))

    if isinstance(raw, dict) and all(isinstance(base[k], int) for k in MEM_KEYS):
        quad = (
            int(base["Socket"]),
            int(base["MemoryController"]),
            int(base["Channel"]),
            int(base["Slot"]),
        )
        if canonical is not None:
            quad = canonical(ctx, quad)
        return dict(zip(MEM_KEYS, quad))

    mapped = locator(ctx) if locator is not None else None
    if mapped is not None:
        sock_i, mc_i, ch_i, sl_i = mapped
        if base["Socket"] is None:
            base["Socket"] = sock_i
        if base["MemoryController"] is None:
            base["MemoryController"] = mc_i
        if base["Channel"] is None:
            base["Channel"] = ch_i
        if base["Slot"] is None:
            base["Slot"] = sl_i

    out: Dict[str, int] = {}
    for k in MEM_KEYS:
        v = base[k]
        if isinstance(v, int):
            out[k] = v

    if not out:
        return raw
    return out


__all__ = ["generate_memory_location"]
