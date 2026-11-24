# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo-specific processor normalizer.

Lenovo DIMMs don't encode the socket in the URL path, so we need to
fetch each DIMM individually and check ``MemoryLocation.Socket``.
This overrides the base prefetch entirely.

GPUs and other processors may omit ``Status`` and ``Model`` while exposing
``Links.PCIeDevice``; we prefetch that chassis ``PCIeDevice`` and merge
``Status`` plus ``Model`` when the processor leaves them unknown or empty.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from normalizers._shared.status_fields import status_field_unknown_or_empty
from redpool.redfish_client import redfish_get_json

from ..._shared.memory_ecc import memory_ecc_mode_enabled
from ...types import NormalizationContext
from .base import BaseProcessorNormalizer, resolve_base_speed, processor_model

_LENOVO_PCIE_DEVICE_KEY = "_lenovo_processor_pcie_device"

_GENERIC_PCIE_DESCRIPTION_PHRASE = "represents the properties of a pciedevice"


_LENOVO_OEM_OVERRIDES: Dict[str, Any] = {
    "BaseSpeedMHz": lambda ctx: (
        ctx.data.get("Oem", {}).get("Lenovo", {}).get("CurrentClockSpeedMHz")
        if (not ctx.config or ctx.config.use_vendor_oem_overrides)
        else ctx.data.get("BaseSpeedMHz")
    ),
    "TotalEnabledCores": lambda ctx: (
        ctx.data.get("Oem", {}).get("Lenovo", {}).get("NumberOfEnabledCores")
        if (not ctx.config or ctx.config.use_vendor_oem_overrides)
        else ctx.data.get("TotalEnabledCores")
    ),
}


def _pcie_device_odata_id(ctx: NormalizationContext) -> Optional[str]:
    links = ctx.data.get("Links")
    if not isinstance(links, dict):
        return None
    ref = links.get("PCIeDevice")
    if not isinstance(ref, dict):
        return None
    oid = ref.get("@odata.id")
    return oid.strip() if isinstance(oid, str) and oid.strip() else None


def _coerce_status_subset(st: Any) -> Dict[str, Any]:
    if not isinstance(st, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in ("Health", "State", "HealthRollup"):
        if k in st and st[k] is not None:
            out[k] = st[k]
    return out


def prefetch_lenovo_processor_pcie_device(ctx: NormalizationContext) -> None:
    """Load ``Links.PCIeDevice`` for merge into ``Status`` / ``Model`` when useful."""
    ctx.prefetched.pop(_LENOVO_PCIE_DEVICE_KEY, None)
    if ctx.client is None:
        return
    pcie_path = _pcie_device_odata_id(ctx)
    if not pcie_path:
        return
    device = redfish_get_json(ctx.client, pcie_path)
    if isinstance(device, dict) and device:
        ctx.prefetched[_LENOVO_PCIE_DEVICE_KEY] = device


def _lenovo_pcie_device(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.prefetched.get(_LENOVO_PCIE_DEVICE_KEY)
    return raw if isinstance(raw, dict) else {}


def effective_lenovo_processor_status(ctx: NormalizationContext) -> Any:
    raw = ctx.data.get("Status")
    base: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    overlay = _coerce_status_subset(_lenovo_pcie_device(ctx).get("Status"))
    out = dict(base)
    for key in ("Health", "State", "HealthRollup"):
        if key not in overlay:
            continue
        nv = overlay[key]
        if nv is None or (isinstance(nv, str) and not str(nv).strip()):
            continue
        if not status_field_unknown_or_empty(out.get(key)):
            continue
        out[key] = nv
    return out if out else (raw if isinstance(raw, dict) else {})


def _pcie_model_candidate(dev: Dict[str, Any]) -> Optional[str]:
    for key in ("Model", "Name"):
        v = dev.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    desc = dev.get("Description")
    if isinstance(desc, str) and desc.strip():
        if _GENERIC_PCIE_DESCRIPTION_PHRASE in desc.casefold():
            return None
        return desc.strip()
    return None


def effective_lenovo_processor_model(ctx: NormalizationContext) -> Any:
    base = processor_model(ctx)
    if base is not None and str(base).strip():
        return base
    cand = _pcie_model_candidate(_lenovo_pcie_device(ctx))
    return cand if cand else base


class LenovoProcessorNormalizer(BaseProcessorNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        """Match DIMMs to processor via ``MemoryLocation.Socket``; enrich GPU from PCIe."""
        prefetch_lenovo_processor_pcie_device(ctx)
        if ctx.config and not (
            ctx.config.build_processor_links or ctx.config.build_memory_summary
        ):
            return

        socket_raw = ctx.data.get("Socket", "")
        parts = socket_raw.split() if socket_raw else []
        socket_num = parts[-1] if parts else None
        if not socket_num:
            return

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
                    mem_socket = mem_data.get("MemoryLocation", {}).get("Socket")
                    if mem_socket is not None and int(mem_socket) == int(socket_num):
                        matched_links.append({"@odata.id": odata_id})
                        capacity = mem_data.get("CapacityMiB")
                        if capacity is not None:
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
            ctx.logger.error(
                f"Error prefetching memory for processor {ctx.data.get('Id')}: {exc}"
            )
            ctx.prefetched.setdefault("memory_links", [])
            ctx.prefetched.setdefault("memory_summary", {})

    def version_overrides(self) -> Dict[str, Dict[str, Any]]:
        return {
            "#Processor.v1_14_0.Processor": _LENOVO_OEM_OVERRIDES,
            "#Processor.v1_16_0.Processor": _LENOVO_OEM_OVERRIDES,
        }

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Status"] = effective_lenovo_processor_status
        m["Model"] = effective_lenovo_processor_model
        m["BaseSpeedMHz"] = lambda ctx: resolve_base_speed(
            ctx, (("Lenovo", "CurrentClockSpeedMHz"),)
        )
        return m
