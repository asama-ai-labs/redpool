# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""The single normalization sequence for one resource document."""

from __future__ import annotations

from typing import Any, Dict

from .base import ResourceNormalizer
from .evaluator import evaluate
from .types import NormalizationContext


def normalize_resource(
    normalizer: ResourceNormalizer, ctx: NormalizationContext
) -> Dict[str, Any]:
    """Prefetch, then field map, then exact-match ``@odata.type`` version overrides."""
    normalizer.prefetch(ctx)
    ctx.logger.debug("Prefetch complete")

    prefetch_body = normalizer.normalized_body_from_prefetch(ctx)
    if prefetch_body is not None:
        ctx.logger.debug("Normalization used prefetch-built full body")
        return prefetch_body

    result: Dict[str, Any] = evaluate(normalizer.field_map(), ctx)
    ctx.logger.debug(f"After field map, keys: {list(result.keys())}")

    odata_type: str = ctx.data.get("@odata.type", "")
    overrides = normalizer.version_overrides()
    if odata_type in overrides:
        ctx.logger.debug(f"Applying version overrides for {odata_type}")
        result.update(evaluate(overrides[odata_type], ctx))

    ctx.logger.debug(f"Normalization complete. Final keys: {list(result.keys())}")
    return result
