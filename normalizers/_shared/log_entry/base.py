# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base LogEntry normalizer; vendor subclasses override ``apply_oem_branch``."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...base import ResourceNormalizer
from ...types import NormalizationContext
from .v161 import (
    LOG_ENTRY_FIELD_MAP_KEYS,
    build_log_entry_v161,
    oem_branch_to_redpool_props,
)


class BaseLogEntryNormalizer(ResourceNormalizer):
    """Shared v1.16.1-shaped LogEntry output; OEM handling via ``apply_oem_branch``."""

    _OEM_BRANCH_KEYS: tuple[str, ...] = ("Hpe", "Dell", "Lenovo", "Supermicro")

    def prefetch(self, ctx: NormalizationContext) -> None:
        ctx.prefetched["__log_entry__"] = build_log_entry_v161(ctx, self)

    def normalized_body_from_prefetch(
        self, ctx: NormalizationContext
    ) -> Optional[Dict[str, Any]]:
        """Sparse v1.16.1 body is built in prefetch; skip field_map (avoids null-filled keys)."""
        return ctx.prefetched.get("__log_entry__")

    def field_map(self) -> Dict[str, Any]:
        return {
            k: (lambda ctx, _k=k: (ctx.prefetched.get("__log_entry__") or {}).get(_k))
            for k in LOG_ENTRY_FIELD_MAP_KEYS
        }

    def enrich_log_entry_oem(
        self,
        out: Dict[str, Any],
        oem_out: Dict[str, Any],
        redpool: Dict[str, Any],
    ) -> None:
        for key in self._OEM_BRANCH_KEYS:
            branch = oem_out.get(key)
            if isinstance(branch, dict):
                self.apply_oem_branch(key, branch, out, redpool)

    def apply_oem_branch(
        self,
        key: str,
        branch: Dict[str, Any],
        out: Dict[str, Any],
        redpool: Dict[str, Any],
    ) -> None:
        """Default: flat redpool copy only (no promotion to standard fields)."""
        redpool.update(oem_branch_to_redpool_props(branch))
