# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Required ``Id`` / ``Name`` / ``@odata.id`` when a capture leaves them empty.

The request path is the URI the proxy already has. The leaf is the resource Id.
"""

from __future__ import annotations

from typing import Any

from .types import NormalizationContext


def resource_leaf(ctx: NormalizationContext) -> str:
    path = (ctx.resource_path or "").rstrip("/")
    if not path:
        return ""
    return path.rsplit("/", 1)[-1]


def id_or_leaf(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Id")
    if isinstance(raw, str) and raw.strip():
        return raw
    leaf = resource_leaf(ctx)
    return leaf if leaf else raw


def name_or_leaf(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Name")
    if isinstance(raw, str) and raw.strip():
        return raw
    return id_or_leaf(ctx)


def odata_id_or_path(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("@odata.id")
    if isinstance(raw, str) and raw.strip():
        return raw
    if ctx.resource_path:
        return ctx.resource_path
    return raw if raw is not None else ""
