# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from .types import NormalizationContext


class ResourceNormalizer(ABC):
    """Two-phase normalizer: *prefetch* then *map*.

    Subclasses implement ``field_map`` (required) and optionally override
    ``prefetch`` and ``version_overrides``.

    Contract:
        * ``prefetch`` is the **only** place that may make API calls.
        * Lambdas returned by ``field_map`` and ``version_overrides`` must
          read exclusively from ``ctx.data`` and ``ctx.prefetched``.
    """

    def prefetch(self, ctx: NormalizationContext) -> None:
        """Phase 1 — fetch additional data and store it in *ctx.prefetched*."""

    def normalized_body_from_prefetch(
        self, ctx: NormalizationContext
    ) -> Optional[Dict[str, Any]]:
        """Return the full normalized body after prefetch, or None to use field_map.

        When non-None, the proxy skips ``field_map`` and ``version_overrides``.
        Use when prefetch already built the complete resource document and
        evaluating ``field_map`` would be wrong or undesirable (for example,
        re-materializing every mapped key with explicit nulls instead of a
        sparse Redfish-shaped dict).

        Default is None (standard two-phase map path).
        """
        return None

    @abstractmethod
    def field_map(self) -> Dict[str, Any]:
        """Phase 2 — return a pure mapping dict.

        Values may be static literals, ``lambda ctx: ...``, or nested dicts.
        """
        ...

    def version_overrides(self) -> Dict[str, Dict[str, Any]]:
        """Optional version-specific field overrides.

        Keys are **exact** ``@odata.type`` strings.  Values are mapping dicts
        in the same format as ``field_map``.
        """
        return {}
