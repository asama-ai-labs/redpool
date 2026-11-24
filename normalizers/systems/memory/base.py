# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base memory normalizer.

Memory resources are relatively standardized across vendors compared to
Processors.  Vendor OEM handling lives in ``dell_memory.py``, ``hpe_memory.py`` and
``lenovo_memory.py``.
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, Optional

from ...base import ResourceNormalizer
from ...optional import omit_if_null, optional
from ...types import NormalizationContext
from ...vendor_id import normalize_vendor_id
from .memory_location import generate_memory_location


def _as_positive_int(v: Any) -> Optional[int]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int) and v > 0:
        return v
    if isinstance(v, float) and v.is_integer():
        i = int(v)
        return i if i > 0 else None
    return None


def _memory_device_type_is_ddr5(memory_device_type: Any) -> bool:
    if not isinstance(memory_device_type, str):
        return False
    return "DDR5" in memory_device_type.upper()


def derive_ecc_bits_from_bus_data_widths(
    data_width_bits: Any,
    bus_width_bits: Any,
    memory_device_type: Any,
) -> Optional[int]:
    """Infer SECDED check-bit count from ``BusWidthBits`` and ``DataWidthBits``.

    **DDR4 and earlier** — one wide data path; extra bus bits are ECC for that path:
    ``ecc_bits = bus_width_bits - data_width_bits``.

    **DDR5** — a logical DIMM exposes two independent subchannels; ``BusWidthBits`` and
    ``DataWidthBits`` are totals across both. ECC is applied per subchannel, so the
    check-bit count for the module is ``(bus_width_bits - data_width_bits) / 2``.

    Returns ``None`` when widths are missing, non-positive, or ``bus <= data``.
    """
    dw = _as_positive_int(data_width_bits)
    bw = _as_positive_int(bus_width_bits)
    if dw is None or bw is None or bw <= dw:
        return None
    delta = bw - dw
    if _memory_device_type_is_ddr5(memory_device_type):
        half = delta // 2
        return half if half > 0 else None
    return delta


def reported_error_correction(ctx: NormalizationContext) -> Any:
    """The BMC's own ``ErrorCorrection`` when it set one, else None."""
    val = ctx.data.get("ErrorCorrection")
    if isinstance(val, str) and val.strip():
        return val
    if val is not None and not isinstance(val, str):
        return val
    return None


def memory_oem(
    ctx: NormalizationContext,
    extend: Optional[
        Callable[[Dict[str, Any], Dict[str, Any], NormalizationContext], None]
    ] = None,
) -> Dict[str, Any]:
    """Preserve vendor ``Oem`` and add ``Oem.Redpool`` for Redpool-only enrichments.

    A vendor passes *extend*, called as ``extend(rp, oem, ctx)``, to add its own fields to
    ``rp`` (the ``Oem.Redpool`` dict) before the generic ECC-bits derivation.
    """
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    rp: Dict[str, Any] = {}
    # Raw BMC Memory has no ``redpool``; a dict appears when re-normalizing saved output or tests.
    existing = out.get("Redpool")
    if isinstance(existing, dict):
        rp = copy.deepcopy(existing)
    rp.pop("SerialNumberIsPlaceholder", None)
    rp.pop("ManufactureDateWWYY", None)

    if extend is not None:
        extend(rp, out, ctx)

    existing_ecc = rp.get("EccBits")
    if not (isinstance(existing_ecc, int) and existing_ecc > 0):
        derived = derive_ecc_bits_from_bus_data_widths(
            ctx.data.get("DataWidthBits"),
            ctx.data.get("BusWidthBits"),
            ctx.data.get("MemoryDeviceType"),
        )
        if derived is not None:
            rp["EccBits"] = derived

    if rp:
        out["Redpool"] = rp
    else:
        out.pop("Redpool", None)
    return out


def memory_manufacturer(raw: Any) -> str:
    """Canonical DIMM manufacturer from the payload's own ``Manufacturer`` value."""
    normalized = normalize_vendor_id(raw if isinstance(raw, str) else None)
    return normalized if isinstance(normalized, str) else ""


def _memory_manufacturer(ctx: NormalizationContext) -> Any:
    return memory_manufacturer(ctx.data.get("Manufacturer"))


def _memory_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    return memory_oem(ctx)


def memory_status(ctx: NormalizationContext) -> Any:
    status = ctx.data.get("Status")
    return dict(status) if isinstance(status, dict) else {}


class BaseMemoryNormalizer(ResourceNormalizer):
    """Vendor-agnostic Memory DIMM normalizer."""

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#Memory.Memory",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Memory.v1_20_0.Memory",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "CapacityMiB": optional("CapacityMiB"),
            "Manufacturer": _memory_manufacturer,
            "PartNumber": lambda ctx: _memory_part_number(ctx),
            "SerialNumber": lambda ctx: _str_or_empty(ctx.data.get("SerialNumber")),
            "MemoryDeviceType": optional("MemoryDeviceType"),
            "MemoryType": optional("MemoryType"),
            "BaseModuleType": optional("BaseModuleType"),
            "OperatingSpeedMhz": optional("OperatingSpeedMhz"),
            "AllowedSpeedsMHz": lambda ctx: ctx.data.get("AllowedSpeedsMHz", []),
            "DataWidthBits": optional("DataWidthBits"),
            "BusWidthBits": optional("BusWidthBits"),
            "RankCount": optional("RankCount"),
            "ErrorCorrection": reported_error_correction,
            "MemoryLocation": omit_if_null(generate_memory_location),
            "Location": lambda ctx: ctx.data.get("Location") or {},
            "DeviceLocator": lambda ctx: _str_or_empty(ctx.data.get("DeviceLocator")),
            "DeviceID": lambda ctx: _str_or_empty(ctx.data.get("DeviceID")),
            "OperatingMemoryModes": lambda ctx: ctx.data.get(
                "OperatingMemoryModes", []
            ),
            "VolatileSizeMiB": optional("VolatileSizeMiB"),
            "MemoryMedia": lambda ctx: ctx.data.get("MemoryMedia", []),
            "Status": memory_status,
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Assembly": lambda ctx: ctx.data.get("Assembly", {}),
            "Metrics": lambda ctx: ctx.data.get("Metrics", {}),
            "Oem": _memory_oem,
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#MemoryCollection.MemoryCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#MemoryCollection.MemoryCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Memory DIMMs for this System",
    "Name": "MemoryCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}


def _str_or_empty(value: Any) -> str:
    """String field present on every model; empty when the BMC omits it."""
    if isinstance(value, str):
        return value
    return ""


def _memory_part_number(ctx: NormalizationContext) -> str:
    raw = ctx.data.get("PartNumber")
    if not ctx.config or ctx.config.strip_memory_part_number:
        raw = _strip(raw)
    return raw if isinstance(raw, str) else ""


def _strip(value: Any) -> Any:
    """Strip trailing whitespace from part numbers (HPE pads with spaces)."""
    if isinstance(value, str):
        return value.strip()
    return value
