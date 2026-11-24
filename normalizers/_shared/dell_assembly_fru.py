# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell Chassis Assembly FRU → ``Oem.Redpool`` field promotion (vendor-specific).

Collectors consume the normalized ``Oem.Redpool`` keys only; they must not parse
Dell ``DeviceFQDD`` or other OEM assembly shapes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple


def parse_dell_assembly_production_date(raw: str) -> Optional[Tuple[int, int, str]]:
    """Parse ``Assemblies[].ProductionDate`` (ISO 8601) → ``(ManufactureWeek, ManufactureYear, ManufactureDate)``.

    Week and year follow :func:`datetime.date.isocalendar`. ``ManufactureDate`` is ``YYYY-MM-DD``.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    d = dt.astimezone(timezone.utc).date()
    iso_y, iso_w, _ = d.isocalendar()
    return (int(iso_w), int(iso_y), d.isoformat())


def assembly_odata_path(ref: str) -> str:
    ref = ref.strip()
    if ref.startswith("http") and "/redfish/" in ref:
        return ref[ref.index("/redfish/") :]
    if ref.startswith("/"):
        return ref
    return f"/redfish/v1/{ref.lstrip('/')}"


def _assembly_member_device_key(block: Dict[str, Any]) -> Optional[str]:
    """Stable device key for an Assemblies[] entry (FQDD / Name without #FRU / MemberId)."""
    oem = block.get("Oem")
    if isinstance(oem, dict):
        dell = oem.get("Dell")
        if isinstance(dell, dict):
            da = dell.get("DellAssembly")
            if isinstance(da, dict):
                fqdd = da.get("DeviceFQDD")
                if isinstance(fqdd, str) and fqdd.strip():
                    return fqdd.strip()
    name = block.get("Name")
    if isinstance(name, str) and name.strip():
        return name.strip().split("#", 1)[0]
    mid = block.get("MemberId")
    if isinstance(mid, str) and mid.strip() and ("." in mid or mid.startswith("PSU")):
        return mid.strip()
    return None


def select_assembly_block(
    data: Dict[str, Any], match_key: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Pick Assemblies[] entry for ``match_key``.

    When ``match_key`` is set (chassis-wide Assembly), never fall back to an
    unrelated member (e.g. a DIMM PartNumber). Without a key, use the first
    block with a PartNumber (per-PSU Assembly docs have a single entry).
    """
    assemblies = data.get("Assemblies") or []
    if not isinstance(assemblies, list):
        return None
    if match_key:
        mk = match_key.casefold()
        for block in assemblies:
            if not isinstance(block, dict):
                continue
            key = _assembly_member_device_key(block)
            if key and key.casefold() == mk:
                return block
            mid = block.get("MemberId")
            if isinstance(mid, str) and mid.strip().casefold() == mk:
                return block
        return None
    for block in assemblies:
        if not isinstance(block, dict):
            continue
        pn = block.get("PartNumber")
        if isinstance(pn, str) and pn.strip():
            return block
    return None


def production_date_from_assembly_payload(
    data: Dict[str, Any], match_key: Optional[str] = None
) -> Optional[str]:
    block = select_assembly_block(data, match_key)
    if block is None:
        return None
    pd = block.get("ProductionDate")
    if isinstance(pd, str) and pd.strip():
        return pd.strip()
    return None


def redpool_fields_from_assembly_block(block: Dict[str, Any]) -> Dict[str, Any]:
    """Map one ``Assemblies[]`` block → ``Oem.Redpool`` FRU / manufacture fields."""
    out: Dict[str, Any] = {}
    pn = block.get("PartNumber")
    if isinstance(pn, str) and pn.strip():
        out["FruPartNumber"] = pn.strip()
    ecl = block.get("EngineeringChangeLevel")
    if isinstance(ecl, str) and ecl.strip():
        out["EngineeringChangeLevel"] = ecl.strip()
    pd = block.get("ProductionDate")
    if isinstance(pd, str) and pd.strip():
        parsed = parse_dell_assembly_production_date(pd.strip())
        if parsed is not None:
            wk, yr, iso_date = parsed
            out["ManufactureWeek"] = wk
            out["ManufactureYear"] = yr
            out["ManufactureDate"] = iso_date
    return out


def redpool_fields_from_assembly_payload(
    data: Dict[str, Any], match_key: Optional[str] = None
) -> Dict[str, Any]:
    """Extract ``Oem.Redpool`` assembly fields from an Assembly document."""
    block = select_assembly_block(data, match_key)
    if block is None and match_key is None:
        if (
            isinstance(data.get("PartNumber"), str)
            and data.get("PartNumber", "").strip()
        ):
            block = data
    if not isinstance(block, dict):
        return {}
    return redpool_fields_from_assembly_block(block)


def merge_redpool_assembly_fields(rp: Dict[str, Any], fields: Dict[str, Any]) -> None:
    """Merge ``fields`` into ``rp`` when target keys are empty."""
    for key, val in fields.items():
        if val is None or val == "":
            continue
        if not rp.get(key):
            rp[key] = val


def fetch_chassis_assembly_redpool_fields(
    client: Any, chassis_odata_path: str, match_key: Optional[str]
) -> Dict[str, Any]:
    """Load ``{chassis}/Assembly`` and return redpool fields for ``match_key``."""
    if client is None or not chassis_odata_path:
        return {}
    path = assembly_odata_path(chassis_odata_path.rstrip("/") + "/Assembly")
    try:
        from redpool.redfish_client import redfish_get_json

        payload = redfish_get_json(client, path)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(payload, dict):
        return {}
    return redpool_fields_from_assembly_payload(payload, match_key)


def dell_chassis_path_from_resource_odata_id(odata_id: str) -> Optional[str]:
    """Derive ``/redfish/v1/Chassis/{id}`` from a Systems or Chassis member URI."""
    if not isinstance(odata_id, str) or not odata_id.strip():
        return None
    path = odata_id.split("#", 1)[0]
    if "/Chassis/" in path:
        return (
            path.split("/Chassis/", 1)[0]
            + "/Chassis/"
            + path.split("/Chassis/", 1)[1].split("/", 1)[0]
        )
    if "/Systems/" in path:
        system_id = path.split("/Systems/", 1)[1].split("/", 1)[0]
        return f"/redfish/v1/Chassis/{system_id}"
    return None
