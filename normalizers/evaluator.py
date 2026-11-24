# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

from __future__ import annotations

from typing import Any

from .optional import OMIT
from .types import NormalizationContext


def evaluate(mapping: Any, ctx: NormalizationContext) -> Any:
    """Recursively evaluate a mapping against a NormalizationContext.

    A value of ``OMIT`` drops that property. Normalizer rules opt in with
    ``optional`` or ``omit_if_null``.
    """
    if callable(mapping):
        return mapping(ctx)
    if isinstance(mapping, dict):
        out: dict[str, Any] = {}
        for key, spec in mapping.items():
            value = evaluate(spec, ctx)
            if value is OMIT:
                continue
            out[key] = value
        return out
    return mapping
