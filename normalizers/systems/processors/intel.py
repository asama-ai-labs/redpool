# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Intel processor: drop IdentificationRegisters that are not hex, and read the CPU
marketing line that Intel M50 / Rack Scale BMCs put in ``ProcessorId.VendorId``."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ...types import NormalizationContext
from ...vendor_id import normalize_vendor_id
from .base import (
    _INTEL_XEON_RE,
    BaseProcessorNormalizer,
    _derive_part_number,
    _intel_xeon_model_is_complete,
    _title_case_tier,
    finalize_processor_model_string,
    processor_model,
    resolve_base_speed,
)

_PCI_REGISTER_RE = re.compile(r"^0x[0-9A-Fa-f]+$")


def _intel_processor_id(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.data.get("ProcessorId")
    pid = dict(raw) if isinstance(raw, dict) else {}
    pid["VendorId"] = normalize_vendor_id(ctx.data.get("Manufacturer"))
    registers = pid.get("IdentificationRegisters")
    if isinstance(registers, str) and not _PCI_REGISTER_RE.match(registers):
        pid.pop("IdentificationRegisters", None)
    return pid


def _xeon_marketing_misplaced_in_vendor_id(ctx: NormalizationContext) -> Optional[str]:
    """Some Intel BMCs (e.g. Intel M50 / Rack Scale) put the full CPU marketing line in
    ProcessorId.VendorId instead of a short PCI vendor string. Detect and return it so we
    can derive Model, PartNumber, and base speed (the Intel module replaces VendorId separately)."""
    pid = ctx.data.get("ProcessorId")
    if not isinstance(pid, dict):
        return None
    vid = pid.get("VendorId")
    if not isinstance(vid, str) or len(vid) < 20:
        return None
    vl = vid.lower()
    if "xeon" not in vl or "intel" not in vl:
        return None
    if "@" in vid or re.search(r"\b(gold|silver|platinum|bronze)\b", vl):
        return vid
    return None


def _is_generic_intel_xeon_model(model: str) -> bool:
    """True when Model is an unhelpful placeholder (no SKU tier/number)."""
    m = (model or "").strip()
    if not m:
        return True
    ml = re.sub(r"\s+", " ", m.lower())
    if re.search(r"\b(gold|silver|platinum|bronze)\b", ml):
        return False
    if re.search(r"\d{4}", m):
        return False
    return "xeon" in ml and "processor" in ml


def _intel_processor_model(ctx: NormalizationContext) -> Any:
    """``Model``, taking the marketing line from ``VendorId`` when ``Model`` is a placeholder."""
    raw = ctx.data.get("Model")
    if isinstance(raw, str) and re.search(r"(?i)xeon", raw):
        raw_s = raw.strip()
        if not _intel_xeon_model_is_complete(raw_s):
            marketing = _xeon_marketing_misplaced_in_vendor_id(ctx)
            if marketing and _is_generic_intel_xeon_model(raw_s):
                return finalize_processor_model_string(marketing.strip(), ctx)
    return processor_model(ctx)


def _intel_part_number(ctx: NormalizationContext) -> Optional[str]:
    raw = ctx.data.get("PartNumber")
    if raw and raw.strip():
        return raw
    if ctx.config and not ctx.config.derive_part_number:
        return raw
    marketing = _xeon_marketing_misplaced_in_vendor_id(ctx)
    if marketing:
        m = _INTEL_XEON_RE.search(marketing)
        if m:
            return f"Xeon {_title_case_tier(m.group(1).strip())}"
    return _derive_part_number(ctx)


def _intel_base_speed(ctx: NormalizationContext) -> Optional[int]:
    marketing = _xeon_marketing_misplaced_in_vendor_id(ctx)
    return resolve_base_speed(ctx, speed_texts=(marketing,) if marketing else ())


class IntelProcessorNormalizer(BaseProcessorNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["ProcessorId"] = _intel_processor_id
        mapping["Model"] = _intel_processor_model
        mapping["PartNumber"] = _intel_part_number
        mapping["BaseSpeedMHz"] = _intel_base_speed
        return mapping
