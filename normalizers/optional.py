# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Field-map helpers for optional Redfish properties.

A field map is a dict, so a missing value has to be a sentinel. ``evaluate``
drops that sentinel. The normalizer rule chooses which properties use it.
"""

from __future__ import annotations

from typing import Any, Callable

from .types import NormalizationContext

OMIT = object()


def optional(key: str) -> Callable[[NormalizationContext], Any]:
    """Copy ``key`` from the payload. Omit the property when the value is null."""

    def _read(ctx: NormalizationContext) -> Any:
        value = ctx.data.get(key)
        return OMIT if value is None else value

    return _read


def omit_if_null(
    fn: Callable[[NormalizationContext], Any],
) -> Callable[[NormalizationContext], Any]:
    """Omit the property when ``fn`` returns null."""

    def _read(ctx: NormalizationContext) -> Any:
        value = fn(ctx)
        return OMIT if value is None else value

    return _read
