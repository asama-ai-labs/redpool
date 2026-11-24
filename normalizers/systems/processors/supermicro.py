# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Supermicro-specific processor normalizer.

Supermicro BMCs use ``MemoryLocation.Socket`` to associate DIMMs with
processors.  Multi-socket systems label CPUs as "CPU1", "CPU2" (1-based),
mapping to MemoryLocation.Socket 0, 1.  Single-socket systems (e.g.
Ampere "CPU 0") take all populated DIMMs.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from redpool.redfish_client import redfish_get_json

from ..._shared.memory_ecc import memory_ecc_mode_enabled
from ...optional import omit_if_null, optional
from ...types import NormalizationContext
from .base import BaseProcessorNormalizer, finalize_processor_model_string


class SupermicroProcessorNormalizer(BaseProcessorNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        if ctx.config and not (
            ctx.config.build_processor_links or ctx.config.build_memory_summary
        ):
            return

        socket_raw = ctx.data.get("Socket", "")
        m = re.search(r"\d+", socket_raw)
        if not m:
            return

        cpu_num = int(m.group(0))
        # "CPU1"/"CPU2" → 1-based → MemoryLocation.Socket = cpu_num - 1
        # "CPU 0" → 0-based single-socket → take ALL populated DIMMs
        single_socket = cpu_num == 0
        target_socket = cpu_num - 1 if not single_socket else 0

        try:
            system_id = ctx.odata_id.split("/")[-3]
            mem_path = f"/redfish/v1/Systems/{system_id}/Memory"
            mem_collection = redfish_get_json(ctx.client, mem_path)
            all_links: List[Dict[str, str]] = mem_collection.get("Members", [])

            matched_links: List[Dict[str, str]] = []
            total_mib = 0
            error_corrections: List[Any] = []

            for lnk in all_links:
                odata_id = lnk.get("@odata.id", "")
                try:
                    mem_data = redfish_get_json(ctx.client, odata_id)
                    capacity = mem_data.get("CapacityMiB")
                    if not capacity:
                        continue

                    mem_socket = mem_data.get("MemoryLocation", {}).get("Socket")
                    if single_socket or mem_socket == target_socket:
                        matched_links.append({"@odata.id": odata_id})
                        total_mib += capacity
                        error_corrections.append(mem_data.get("ErrorCorrection"))
                except Exception as exc:
                    ctx.logger.error(f"Error processing memory link {odata_id}: {exc}")

            ctx.prefetched["memory_links"] = matched_links
            ctx.prefetched["memory_summary"] = {
                "TotalMemorySizeMiB": total_mib,
                "ECCModeEnabled": memory_ecc_mode_enabled(error_corrections),
            }
        except Exception as exc:
            ctx.logger.error(f"Error prefetching memory data: {exc}")
            ctx.prefetched.setdefault("memory_links", [])
            ctx.prefetched.setdefault("memory_summary", {})

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        # Only Supermicro sends MaxTDPWatts (the configurable TDP ceiling).
        m["MaxTDPWatts"] = optional("MaxTDPWatts")
        # Some Supermicro BMCs send only MaxTDPWatts. Use it as TDPWatts when no TDPWatts is sent.
        m["TDPWatts"] = omit_if_null(_supermicro_tdp_watts)
        return m

    def version_overrides(self) -> Dict[str, Dict[str, Any]]:
        return {
            "#Processor.v1_11_0.Processor": {
                "Model": lambda ctx: _resolve_model(ctx),
                "ProcessorArchitecture": lambda ctx: _resolve_arch(ctx),
                "InstructionSet": lambda ctx: _resolve_instruction_set(ctx),
            },
        }


def _supermicro_tdp_watts(ctx: NormalizationContext) -> Any:
    """``TDPWatts`` from the BMC, else its ``MaxTDPWatts``."""
    tdp = ctx.data.get("TDPWatts")
    if tdp is not None:
        return tdp
    return ctx.data.get("MaxTDPWatts")


def _is_ampere(ctx: NormalizationContext) -> bool:
    """Return True if the processor is an Ampere (Manufacturer contains 'ampere')."""
    return "ampere" in (ctx.data.get("Manufacturer") or "").lower()


def _resolve_model(ctx: NormalizationContext) -> Optional[str]:
    """``Model`` from the BMC, except the Ampere + Supermicro case we intentionally enrich.

    When ``enrich_ampere_model`` is on (default) and ``PartNumber`` is set, replace the
    generic BMC ``Model`` with ``Ampere(R) Altra(R) {PartNumber}``. Otherwise apply the same
    Intel Xeon ``Model`` normalization as ``BaseProcessorNormalizer`` (same as base).
    """
    if _is_ampere(ctx) and (not ctx.config or ctx.config.enrich_ampere_model):
        pn = ctx.data.get("PartNumber")
        if pn:
            return f"Ampere(R) Altra(R) {pn}"
    raw = ctx.data.get("Model")
    if isinstance(raw, str):
        return finalize_processor_model_string(raw, ctx)
    return raw


def _resolve_arch(ctx: NormalizationContext) -> Optional[str]:
    """ProcessorArchitecture: use raw value if present; for Ampere default to 'ARM'."""
    raw = ctx.data.get("ProcessorArchitecture")
    if raw:
        return raw
    if _is_ampere(ctx):
        return "ARM"
    return None


def _resolve_instruction_set(ctx: NormalizationContext) -> Optional[str]:
    """InstructionSet: use raw value if present; for Ampere default to 'ARM-A64'."""
    raw = ctx.data.get("InstructionSet")
    if raw:
        return raw
    if _is_ampere(ctx):
        return "ARM-A64"
    return None
