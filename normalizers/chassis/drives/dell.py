# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell Drive normalization: DellPhysicalDisk and Links.Oem.Dell fields.

The same overrides serve Chassis/Drives and Systems/Storage/Drives
(see ``systems/storage/drives/dell.py``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ...optional import omit_if_null
from ...types import NormalizationContext
from .base import (
    BaseChassisDriveNormalizer,
    clean_part_number,
    drive_failure_predicted,
    drive_identifiers,
    drive_model,
    drive_oem,
    drive_part_number,
)


def _physical_disk(oem: Any) -> Optional[Dict[str, Any]]:
    """``Oem.Dell.DellPhysicalDisk`` when present."""
    if isinstance(oem, dict):
        dell = oem.get("Dell")
        if isinstance(dell, dict):
            disk = dell.get("DellPhysicalDisk")
            if isinstance(disk, dict):
                return disk
    return None


def _dell_failure_predicted(ctx: NormalizationContext) -> Any:
    fp = drive_failure_predicted(ctx)
    if isinstance(fp, bool):
        return fp
    disk = _physical_disk(ctx.data.get("Oem"))
    if disk is not None:
        pred = disk.get("PredictiveFailureState")
        if isinstance(pred, str):
            pl = pred.strip().lower()
            if pl in ("true", "yes", "failed", "predictive failure", "smartalert"):
                return True
            # iDRAC uses SmartAlertAbsent when no predictive failure.
            if pl in ("false", "no", "ok", "smart", "smartalertabsent"):
                return False
        if isinstance(pred, bool):
            return pred
    return fp


def _dell_identifiers(ctx: NormalizationContext) -> Any:
    """Pass through Identifiers; synthesize NAA from DellPhysicalDisk.WWN when empty."""
    ids = ctx.data.get("Identifiers")
    if isinstance(ids, list) and ids:
        return ids
    disk = _physical_disk(ctx.data.get("Oem"))
    if disk is not None:
        wwn = disk.get("WWN")
        if isinstance(wwn, str) and wwn.strip():
            return [{"DurableName": wwn.strip(), "DurableNameFormat": "NAA"}]
    return drive_identifiers(ctx)


def _dell_part_number(ctx: NormalizationContext) -> Any:
    """Prefer PartNumber; fall back to DellPhysicalDisk.ProductID when BMC says Not Available."""
    cleaned = clean_part_number(ctx)
    if cleaned is not None:
        return cleaned
    pn = drive_part_number(ctx)
    model = drive_model(ctx)
    model_s = model.strip() if isinstance(model, str) else ""
    disk = _physical_disk(ctx.data.get("Oem"))
    if disk is not None:
        pid = disk.get("ProductID")
        if isinstance(pid, (str, int, float)) and str(pid).strip():
            pid_s = str(pid).strip()
            if model_s and pid_s.casefold() == model_s.casefold():
                return pn
            return pid_s
    return pn


def _dell_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    """Preserve raw Oem; promote DellPhysicalDisk predictive/RAID/spare fields into Oem.Redpool.

    Also promote Links.Oem.Dell.CPUAffinity processor refs for collector cpu_affinity labels.
    """
    out = drive_oem(ctx)
    rp: Dict[str, Any] = (
        dict(out.get("Redpool") or {}) if isinstance(out.get("Redpool"), dict) else {}
    )
    disk = _physical_disk(out)
    if disk is not None:
        spare = disk.get("AvailableSparePercent")
        if isinstance(spare, (int, float)):
            rp["AvailableSparePercent"] = spare
        for key in ("PredictiveFailureState", "RaidStatus"):
            val = disk.get(key)
            if isinstance(val, str) and val.strip():
                rp[key] = val.strip()
        pid = disk.get("ProductID")
        if isinstance(pid, (str, int, float)) and str(pid).strip():
            rp["ProductID"] = str(pid).strip()
    # CPUAffinity lives under Links.Oem.Dell, not Oem.DellPhysicalDisk.
    links = ctx.data.get("Links")
    if isinstance(links, dict):
        loem = links.get("Oem")
        if isinstance(loem, dict):
            ldell = loem.get("Dell")
            if isinstance(ldell, dict):
                aff = ldell.get("CPUAffinity")
                if isinstance(aff, list):
                    refs: list[str] = []
                    for item in aff:
                        if not isinstance(item, dict):
                            continue
                        oid = item.get("@odata.id")
                        if isinstance(oid, str) and oid.strip():
                            refs.append(oid.strip().rstrip("/").rsplit("/", 1)[-1])
                    if refs:
                        rp["CPUAffinity"] = ",".join(refs)
    if rp:
        out["Redpool"] = rp
    return out


def dell_drive_field_map(mapping: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the Dell overrides to a Drive field map."""
    mapping["PartNumber"] = omit_if_null(_dell_part_number)
    mapping["FailurePredicted"] = _dell_failure_predicted
    mapping["Identifiers"] = _dell_identifiers
    mapping["Oem"] = _dell_oem
    return mapping


class DellChassisDriveNormalizer(BaseChassisDriveNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return dell_drive_field_map(super().field_map())
