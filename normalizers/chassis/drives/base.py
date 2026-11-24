# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Drive normalizer for Chassis-level drives."""

from __future__ import annotations

import copy
from typing import Any, Dict, Optional

from ...base import ResourceNormalizer
from ...optional import omit_if_null, optional
from ...types import NormalizationContext
from ...vendor_id import (
    manufacturer_from_storage_model,
    normalize_drive_manufacturer,
)


def drive_model(ctx: NormalizationContext) -> Any:
    """Keep BMC ``Model`` (part/SKU) when set, else ``""``. ``Name`` is a slot label, not a model."""
    model = ctx.data.get("Model")
    if isinstance(model, str) and model.strip():
        return model.strip()
    return ""


def _drive_manufacturer(ctx: NormalizationContext) -> Optional[str]:
    mfr = normalize_drive_manufacturer(
        ctx.data.get("Manufacturer"), ctx.data.get("Model")
    )
    if isinstance(mfr, str) and mfr.strip():
        return mfr
    for key in ("Model", "Name"):
        val = ctx.data.get(key)
        if isinstance(val, str) and val.strip():
            inferred = manufacturer_from_storage_model(val.strip())
            if inferred:
                return inferred
    # No fallback to the server vendor: a drive from another maker would be misattributed.
    return mfr


def drive_failure_predicted(ctx: NormalizationContext) -> Any:
    return ctx.data.get("FailurePredicted")


def drive_identifiers(ctx: NormalizationContext) -> Any:
    ids = ctx.data.get("Identifiers")
    if isinstance(ids, list) and ids:
        return ids
    return ids if ids is not None else []


_PART_NUMBER_PLACEHOLDERS = (
    "not available",
    "n/a",
    "na",
    "none",
    "unknown",
    "notapplicable",
)


def clean_part_number(ctx: NormalizationContext) -> Optional[str]:
    """``PartNumber`` stripped, or None when the BMC left it empty or a placeholder."""
    pn = ctx.data.get("PartNumber")
    if isinstance(pn, str) and pn.strip():
        if pn.strip().lower() not in _PART_NUMBER_PLACEHOLDERS:
            return pn.strip()
    return None


def drive_part_number(ctx: NormalizationContext) -> Any:
    cleaned = clean_part_number(ctx)
    return cleaned if cleaned is not None else ctx.data.get("PartNumber")


def drive_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    """Preserve the raw Oem."""
    src = ctx.data.get("Oem")
    return copy.deepcopy(src) if isinstance(src, dict) else {}


class BaseChassisDriveNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return drive_field_map()


def drive_field_map() -> Dict[str, Any]:
    """Common Drive field map, reusable across Chassis/Drives and Systems/Storage/Drives."""
    return {
        "@odata.context": "/redfish/v1/$metadata#Drive.Drive",
        "@odata.etag": optional("@odata.etag"),
        "@odata.id": lambda ctx: ctx.odata_id,
        "@odata.type": "#Drive.v1_19_0.Drive",
        "Id": lambda ctx: ctx.data.get("Id"),
        "Name": lambda ctx: ctx.data.get("Name"),
        "Description": omit_if_null(
            lambda ctx: ctx.data.get("Description") or ctx.data.get("Name")
        ),
        "StatusIndicator": optional("StatusIndicator"),
        "Model": drive_model,
        "Manufacturer": _drive_manufacturer,
        "SerialNumber": optional("SerialNumber"),
        "PartNumber": omit_if_null(drive_part_number),
        "Revision": optional("Revision"),
        "MediaType": optional("MediaType"),
        "Protocol": optional("Protocol"),
        "CapacityBytes": optional("CapacityBytes"),
        "BlockSizeBytes": optional("BlockSizeBytes"),
        "RotationSpeedRPM": optional("RotationSpeedRPM"),
        "CapableSpeedGbs": optional("CapableSpeedGbs"),
        "NegotiatedSpeedGbs": optional("NegotiatedSpeedGbs"),
        "PredictedMediaLifeLeftPercent": optional("PredictedMediaLifeLeftPercent"),
        "FailurePredicted": drive_failure_predicted,
        "IndicatorLED": optional("IndicatorLED"),
        "LocationIndicatorActive": optional("LocationIndicatorActive"),
        "HotspareType": optional("HotspareType"),
        "EncryptionAbility": optional("EncryptionAbility"),
        "EncryptionStatus": optional("EncryptionStatus"),
        "WriteCacheEnabled": optional("WriteCacheEnabled"),
        "Identifiers": drive_identifiers,
        "PhysicalLocation": lambda ctx: ctx.data.get("PhysicalLocation", {}),
        # Deprecated since Drive v1_4 in favor of PhysicalLocation. Pass it through only
        # when the BMC sent it; do not default it to [].
        "Location": optional("Location"),
        "Status": lambda ctx: ctx.data.get("Status", {}),
        "Links": lambda ctx: ctx.data.get("Links", {}),
        "Actions": lambda ctx: ctx.data.get("Actions", {}),
        "Assembly": lambda ctx: ctx.data.get("Assembly", {}),
        "Operations": lambda ctx: ctx.data.get("Operations", []),
        "Oem": drive_oem,
    }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#DriveCollection.DriveCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#DriveCollection.DriveCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Drives",
    "Name": "DriveCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
