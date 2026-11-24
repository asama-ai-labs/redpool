# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base processor normalizer with shared prefetch and field-map logic.

Vendor subclasses override ``memory_dimm_pattern`` (and optionally
``prefetch`` / ``version_overrides``) — everything else is inherited.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from redpool.redfish_client import redfish_get_json

from ..._shared.memory_ecc import memory_ecc_mode_enabled
from ...base import ResourceNormalizer
from ...optional import optional
from ...types import NormalizationContext
from ...vendor_id import normalize_vendor_id

_INTEL_XEON_RE = re.compile(
    r"(?i)xeon\(r\)\s+(?:cpu\s+)?(.+?)(?:\s+cpu(?:\s|$)|\s*@|\s*$)"
)
_AMD_EPYC_RE = re.compile(r"(?i)(epyc)\s+(\w+)")

_XEON_TIERS = {"gold", "silver", "bronze", "platinum", "w"}

_SPEED_RE = re.compile(r"@\s*([\d.]+)\s*GHz", re.IGNORECASE)

_INTEL_XEON_PREFIX_RE = re.compile(r"(?i)^\s*intel\(r\)\s+xeon\(r\)\s+(.+)\s*$")
# Scalable: ``... Gold 6430 CPU @ 2.10GHz``; legacy: ``... CPU E5-2650 v4 @ 2.20GHz``.
_INTEL_XEON_CPU_AT_GHZ_SUFFIX_RE = re.compile(r"(?i)\s+cpu\s+@\s*[\d.]+\s*GHz\s*$")
_INTEL_XEON_AT_GHZ_SUFFIX_RE = re.compile(r"(?i)\s+@\s*[\d.]+\s*GHz\s*$")
_INTEL_XEON_LEGACY_CPU_WORD_RE = re.compile(r"(?i)(Intel\(R\) Xeon\(R\))\s+CPU\s+")


def _intel_xeon_model_is_complete(raw: str) -> bool:
    """True when BMC Model already looks like a full scalable Intel marketing line."""
    s = (raw or "").strip()
    if not s:
        return False
    sl = s.lower()
    if "xeon" not in sl:
        return False
    if _SPEED_RE.search(s) is None:
        return False
    return bool(re.search(r"\bcpu\s+@", sl))


def processor_model(ctx: NormalizationContext) -> Any:
    """Normalize processor ``Model`` for common vendor shapes: Intel Xeon, AMD EPYC.

    Intel: short form (e.g. ``Intel(R) Xeon(R) Gold 5317``, ``Intel(R) Xeon(R) E5-2650 v4``).

    Other string ``Model`` values: whitespace collapsed to single spaces; non-strings unchanged.
    """
    raw = ctx.data.get("Model")
    if raw is None:
        return None
    if not isinstance(raw, str):
        return raw
    raw_s = raw.strip()
    if re.search(r"(?i)xeon", raw_s):
        if _intel_xeon_model_is_complete(raw_s):
            return finalize_processor_model_string(raw_s, ctx)
        return finalize_processor_model_string(raw_s, ctx)
    return _collapse_whitespace_strip(raw)


def _title_case_tier(sku: str) -> str:
    """Normalize Intel tier keywords (PLATINUM -> Platinum) while
    leaving SKU numbers and version suffixes untouched."""
    parts = sku.split(None, 1)
    if parts and parts[0].lower() in _XEON_TIERS:
        parts[0] = parts[0].capitalize()
    return " ".join(parts)


def _collapse_whitespace_strip(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _normalize_intel_xeon_display_model(s: str) -> str:
    """Normalize Intel(R) Xeon(R) prefix and tier keyword casing (e.g. PLATINUM -> Platinum)."""
    m = _INTEL_XEON_PREFIX_RE.match(s)
    if not m:
        return s
    rest = m.group(1).strip()
    parts = rest.split(None, 1)
    if parts and parts[0].lower() in _XEON_TIERS:
        parts[0] = parts[0].capitalize()
        rest = parts[0] if len(parts) == 1 else f"{parts[0]} {parts[1]}"
    return f"Intel(R) Xeon(R) {rest}"


def _strip_intel_xeon_cpu_speed_suffix(s: str) -> str:
    """Drop trailing GHz clauses from Intel Xeon marketing ``Model`` strings."""
    if not re.search(r"(?i)intel\(r\)\s+xeon\(r\)", s):
        return s
    s = _INTEL_XEON_CPU_AT_GHZ_SUFFIX_RE.sub("", s).strip()
    s = _INTEL_XEON_AT_GHZ_SUFFIX_RE.sub("", s).strip()
    return s


def _drop_intel_xeon_legacy_cpu_word(s: str) -> str:
    """``Intel(R) Xeon(R) CPU E5-…`` → ``Intel(R) Xeon(R) E5-…``."""
    if not re.search(r"(?i)intel\(r\)\s+xeon\(r\)", s):
        return s
    return _INTEL_XEON_LEGACY_CPU_WORD_RE.sub(r"\1 ", s).strip()


def finalize_processor_model_string(s: str, _ctx: NormalizationContext) -> str:
    s = _collapse_whitespace_strip(s)
    if not s:
        return s
    s = _normalize_intel_xeon_display_model(s)
    s = _strip_intel_xeon_cpu_speed_suffix(s)
    s = _drop_intel_xeon_legacy_cpu_word(s)
    return s


def _derive_part_number(ctx: NormalizationContext) -> Optional[str]:
    """Return PartNumber from raw data, or derive it from Model for
    Intel Xeon / AMD EPYC when the BMC leaves it empty. Fallback: strip
    common suffixes from Model so other vendors still get a part-like value."""
    raw = ctx.data.get("PartNumber")
    if raw and raw.strip():
        return raw

    if ctx.config and not ctx.config.derive_part_number:
        return raw

    model = (ctx.data.get("Model") or "").strip()
    if not model:
        return None

    m = _INTEL_XEON_RE.search(model)
    if m:
        return f"Xeon {_title_case_tier(m.group(1).strip())}"

    m = _AMD_EPYC_RE.search(model)
    if m:
        return f"EPYC {m.group(2)}"

    # Fallback for other vendors: use Model with common suffixes stripped
    fallback = model
    # Literal suffixes (strip from end)
    for suffix in (" Processor", " CPU", " Core", "-Core", " Thread", "-Thread"):
        if fallback.endswith(suffix) or fallback.lower().endswith(suffix.lower()):
            fallback = fallback[: -len(suffix)].strip()
    # "@ X.XXGHz" and " 12-Core" etc.
    fallback = re.sub(r"\s*@\s*[\d.]+\s*GHz\s*$", "", fallback, flags=re.IGNORECASE)
    fallback = re.sub(
        r"\s+\d+[- ]?(?:Core|Thread)s?\s*$", "", fallback, flags=re.IGNORECASE
    )
    fallback = re.sub(r"\s+", " ", fallback).strip()
    return fallback or model


# ------------------------------------------------------------------
# Smart fallback helpers — used by the base field_map so that ALL
# vendors benefit without needing explicit version_overrides.
# ------------------------------------------------------------------


def resolve_base_speed(
    ctx: NormalizationContext,
    oem_paths: tuple[tuple[str, ...], ...] = (),
    speed_texts: tuple[str, ...] = (),
) -> Optional[int]:
    """BaseSpeedMHz chain: explicit (>0) -> OperatingSpeedMHz (>0) -> vendor OEM paths ->
    GHz in ``speed_texts`` (strings a vendor keeps the clock in) -> GHz in ``Model``.

    BMCs often send ``BaseSpeedMHz: 0`` or omit base while encoding nominal GHz in ``Model``
    (or the full line in ``ProcessorId.VendorId``). Treat non-positive explicit values as
    absent so we still derive from strings; honor literal ``0`` only when derivation is off.
    """
    raw_base = ctx.data.get("BaseSpeedMHz")
    explicit: Optional[int] = None
    if raw_base is not None:
        try:
            explicit = int(float(raw_base))
        except (TypeError, ValueError):
            explicit = 0

    allow_derive = ctx.config is None or ctx.config.derive_base_speed

    if explicit is not None and explicit > 0:
        return explicit
    if explicit is not None and not allow_derive:
        return explicit
    if not allow_derive:
        return None

    val = ctx.data.get("OperatingSpeedMHz")
    if val is not None:
        try:
            op = int(float(val))
        except (TypeError, ValueError):
            op = 0
        if op > 0:
            return op

    def _pos_oem_mhz(path: tuple[str, ...]) -> Optional[int]:
        cur: Any = ctx.data.get("Oem") or {}
        for key in path:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(key)
        if cur is None:
            return None
        try:
            v = int(float(cur))
        except (TypeError, ValueError):
            return None
        return v if v > 0 else None

    if ctx.config is None or ctx.config.use_vendor_oem_overrides:
        # Vendor OEM clock paths come from the vendor's normalizer (HPE, Lenovo).
        for path in oem_paths:
            oem_mhz = _pos_oem_mhz(path)
            if oem_mhz is not None:
                return oem_mhz

    for text in speed_texts:
        sm = _SPEED_RE.search(text)
        if sm:
            try:
                return int(float(sm.group(1)) * 1000)
            except (ValueError, OverflowError):
                pass
    model = ctx.data.get("Model") or ""
    m = _SPEED_RE.search(model)
    if m:
        try:
            return int(float(m.group(1)) * 1000)
        except (ValueError, OverflowError):
            pass
    return None


def _build_links(ctx: NormalizationContext) -> Dict[str, Any]:
    """Return original Links, enriched with prefetched Memory links
    when the original lacks them."""
    original = ctx.data.get("Links") or {}
    if ctx.config and not ctx.config.build_processor_links:
        return original
    memory_links = ctx.prefetched.get("memory_links")
    if memory_links and not original.get("Memory"):
        result = dict(original)
        result["Memory"] = memory_links
        result["Memory@odata.count"] = len(memory_links)
        return result
    return original


def _build_memory_summary(ctx: NormalizationContext) -> Dict[str, Any]:
    """Return original MemorySummary if populated, otherwise use
    the summary built during prefetch."""
    original = ctx.data.get("MemorySummary") or {}
    if original:
        return original
    if ctx.config and not ctx.config.build_memory_summary:
        return original
    return ctx.prefetched.get("memory_summary") or {}


class BaseProcessorNormalizer(ResourceNormalizer):
    """Vendor-agnostic processor normalizer.

    Provides a shared ``prefetch`` that fetches Memory collection data
    when ``memory_dimm_pattern`` returns a pattern, and a canonical
    ``field_map`` covering all standard Processor fields.
    """

    # ------------------------------------------------------------------
    # Extension point: override in vendor subclasses
    # ------------------------------------------------------------------

    def memory_dimm_pattern(self, ctx: NormalizationContext) -> Optional[re.Pattern]:
        """Return a compiled regex that matches the ``@odata.id`` of DIMMs
        belonging to *this* processor, or ``None`` to skip memory prefetch."""
        return None

    # ------------------------------------------------------------------
    # Prefetch — the ONLY place API calls are allowed
    # ------------------------------------------------------------------

    def prefetch(self, ctx: NormalizationContext) -> None:
        if ctx.config and not (
            ctx.config.build_processor_links or ctx.config.build_memory_summary
        ):
            return

        pattern = self.memory_dimm_pattern(ctx)
        if pattern is None:
            return

        try:
            system_id = ctx.odata_id.split("/")[-3]
            mem_path = f"/redfish/v1/Systems/{system_id}/Memory"
            mem_collection = redfish_get_json(ctx.client, mem_path)
            all_links: List[Dict[str, str]] = mem_collection.get("Members", [])

            matched = [
                lnk for lnk in all_links if pattern.search(lnk.get("@odata.id", ""))
            ]
            ctx.prefetched["memory_links"] = [
                {"@odata.id": lnk["@odata.id"]} for lnk in matched
            ]

            total_mib = 0
            error_corrections: List[Any] = []
            for lnk in matched:
                mem_data = redfish_get_json(ctx.client, lnk["@odata.id"])
                capacity = mem_data.get("CapacityMiB")
                if capacity is not None:
                    total_mib += capacity
                    error_corrections.append(mem_data.get("ErrorCorrection"))

            ctx.prefetched["memory_summary"] = {
                "TotalMemorySizeMiB": total_mib,
                "ECCModeEnabled": memory_ecc_mode_enabled(error_corrections),
            }
        except Exception as exc:
            ctx.logger.error(f"Error prefetching memory data: {exc}")
            ctx.prefetched.setdefault("memory_links", [])
            ctx.prefetched.setdefault("memory_summary", {})

    # ------------------------------------------------------------------
    # Field map — pure readers, no API calls
    # ------------------------------------------------------------------

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Processor.Processor",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Processor.v1_20_0.Processor",
            "Assembly": lambda ctx: ctx.data.get("Assembly", {}),
            "Description": lambda ctx: ctx.data.get("Description") or "",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "ProcessorId": lambda ctx: ctx.data.get("ProcessorId", {}),
            "ProcessorType": lambda ctx: (
                (ctx.data.get("ProcessorType") or "").strip() or "CPU"
            ),
            "ProcessorArchitecture": optional("ProcessorArchitecture"),
            "InstructionSet": optional("InstructionSet"),
            "Links": lambda ctx: _build_links(ctx),
            "Manufacturer": lambda ctx: normalize_vendor_id(
                ctx.data.get("Manufacturer")
            ),
            "MemorySummary": lambda ctx: _build_memory_summary(ctx),
            "Model": processor_model,
            "PartNumber": lambda ctx: _derive_part_number(ctx),
            "SerialNumber": lambda ctx: ctx.data.get("SerialNumber") or "",
            "BaseSpeedMHz": lambda ctx: resolve_base_speed(ctx),
            "MaxSpeedMHz": optional("MaxSpeedMHz"),
            "OperatingSpeedMHz": optional("OperatingSpeedMHz"),
            "TDPWatts": optional("TDPWatts"),
            "ProcessorMemory": lambda ctx: ctx.data.get("ProcessorMemory") or [],
            "TotalCores": optional("TotalCores"),
            "TotalThreads": optional("TotalThreads"),
            "TotalEnabledCores": lambda ctx: ctx.data.get("TotalEnabledCores"),
            "Socket": optional("Socket"),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Metrics": lambda ctx: ctx.data.get("Metrics", {}),
            "EnvironmentMetrics": lambda ctx: ctx.data.get("EnvironmentMetrics", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#ProcessorCollection.ProcessorCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#ProcessorCollection.ProcessorCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Processors for this System",
    "Name": "ProcessorCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
