# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Power normalizer (old-style monolithic Power resource).

Contains embedded arrays: PowerControl, PowerSupplies, Redundancy, Voltages.
Normalizes PowerSupplies so LineInputVoltage, PowerInputWatts, LastPowerOutputWatts
(or PowerOutputWatts), and Status are consistently present. PowerCapacityWatts
is passed through as reported by the backend; vendor normalizers may derive it
from other fields (e.g. InputRanges, Model).

When the backend Power resource has no PowerSupplies (e.g. vendor exposes only
PowerSubsystem/PowerSupplies), prefetch fills PowerSupplies from that collection
so the canonical response always has PowerSupplies for generic clients.
"""

from __future__ import annotations

from typing import Any, Dict, List

from redpool.redfish_client import redfish_get_json

from ...base import ResourceNormalizer
from ...optional import optional
from ...types import NormalizationContext
from ...vendor_id import manufacturer_from_model, normalize_power_supply_manufacturer


def _power_supply_part_number(item: Dict[str, Any]) -> Any:
    """Use ``PartNumber`` when set; else ``SparePartNumber`` (HPE often leaves PartNumber null)."""
    pn = item.get("PartNumber")
    if isinstance(pn, str):
        if pn.strip():
            return pn
    elif pn is not None:
        return pn
    spare = item.get("SparePartNumber")
    if isinstance(spare, str):
        s = spare.strip()
        return s if s else None
    return spare


def _embedded_psu_manufacturer(item: Dict[str, Any], ctx: NormalizationContext) -> Any:
    """Match ``PowerSupply`` normalizer: payload ``Manufacturer`` only, never the server vendor."""
    m = item.get("Manufacturer")
    if isinstance(m, str) and m.strip():
        return normalize_power_supply_manufacturer(m.strip())
    if m is not None and not isinstance(m, str):
        return m
    return manufacturer_from_model(item.get("Model"))


def power_supply_hot_pluggable(item: Dict[str, Any]) -> Any:
    """The standard ``HotPluggable`` property. Vendors that report it elsewhere override this."""
    return item.get("HotPluggable")


def normalize_power_supply(
    item: Any, ctx: NormalizationContext | None = None
) -> Dict[str, Any]:
    """Ensure canonical power supply fields for input volts, input/output watts, status.
    PowerCapacityWatts is passed through from item; vendor normalizers may override
    PowerSupplies to derive it from InputRanges or Model.
    """
    if not isinstance(item, dict):
        return {}
    out = dict(item)
    out["PartNumber"] = _power_supply_part_number(item)
    out["LineInputVoltage"] = item.get("LineInputVoltage")
    out["PowerInputWatts"] = item.get("PowerInputWatts")
    out["LastPowerOutputWatts"] = item.get("LastPowerOutputWatts") or item.get(
        "PowerOutputWatts"
    )
    if (
        out.get("LastPowerOutputWatts") is None
        and item.get("PowerOutputWatts") is not None
    ):
        out["LastPowerOutputWatts"] = item["PowerOutputWatts"]
    out["Status"] = item.get("Status") or {}
    out["HotPluggable"] = power_supply_hot_pluggable(item)
    if ctx is not None:
        out["Manufacturer"] = _embedded_psu_manufacturer(item, ctx)
    return out


def _power_supplies_from_power_subsystem(
    ctx: NormalizationContext,
) -> List[Dict[str, Any]]:
    """Fetch PowerSubsystem/PowerSupplies and members, return list in Power.PowerSupplies shape."""
    odata_id = (ctx.odata_id or "").strip()
    if "/Power" not in odata_id:
        return []
    base = odata_id.replace("/Power", "").rstrip("/")
    coll_path = f"{base}/PowerSubsystem/PowerSupplies"
    try:
        data = redfish_get_json(ctx.client, coll_path)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict):
        return []
    members = data.get("Members") or data.get("members") or []
    if not isinstance(members, list):
        return []
    result: List[Dict[str, Any]] = []
    for m in members:
        if isinstance(m, str):
            ref = m
        elif isinstance(m, dict):
            ref = m.get("@odata.id")
        else:
            ref = None
        if not ref:
            continue
        path = ref if ref.startswith("/") else f"/redfish/v1/{ref.lstrip('/')}"
        if path.startswith("http") and "/redfish/" in path:
            path = path[path.index("/redfish/") :]
        try:
            item = redfish_get_json(ctx.client, path)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(item, dict):
            result.append(item)
    return result


def normalize_power_supplies(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    """Return normalized PowerSupplies list (from backend or prefetched PowerSubsystem)."""
    raw = ctx.data.get("PowerSupplies") or []
    if isinstance(raw, list) and len(raw) > 0:
        out = [normalize_power_supply(x, ctx) for x in raw]
    else:
        # Prefetched from PowerSubsystem when backend Power had no PowerSupplies
        prefetched = ctx.prefetched.get("PowerSupplies") if ctx.prefetched else None
        if isinstance(prefetched, list) and len(prefetched) > 0:
            out = [normalize_power_supply(x, ctx) for x in prefetched]
        else:
            return []
    return out


class BasePowerNormalizer(ResourceNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        """If Power has no PowerSupplies, fill from PowerSubsystem/PowerSupplies when present."""
        raw = ctx.data.get("PowerSupplies") or []
        if isinstance(raw, list) and len(raw) > 0:
            pass
        else:
            merged = _power_supplies_from_power_subsystem(ctx)
            if merged:
                if ctx.prefetched is None:
                    ctx.prefetched = {}
                ctx.prefetched["PowerSupplies"] = merged

    def field_map(self) -> Dict[str, Any]:
        def power_supplies_count(ctx: NormalizationContext) -> Any:
            supplies = normalize_power_supplies(ctx)
            return (
                len(supplies) if supplies else ctx.data.get("PowerSupplies@odata.count")
            )

        return {
            "@odata.context": "/redfish/v1/$metadata#Power.Power",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#Power.v1_7_3.Power",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "PowerControl": lambda ctx: ctx.data.get("PowerControl", []),
            "PowerControl@odata.count": optional("PowerControl@odata.count"),
            "PowerSupplies": normalize_power_supplies,
            "PowerSupplies@odata.count": power_supplies_count,
            "Redundancy": lambda ctx: ctx.data.get("Redundancy", []),
            "Redundancy@odata.count": optional("Redundancy@odata.count"),
            "Voltages": lambda ctx: ctx.data.get("Voltages", []),
            "Voltages@odata.count": optional("Voltages@odata.count"),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }
