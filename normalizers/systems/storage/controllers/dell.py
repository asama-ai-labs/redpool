# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell PERC StorageController: surface DellControllerBattery as a standard Battery.

Dell iDRAC only exposes RAID controller battery status as
``Oem.Dell.DellOemResources.DellControllerBattery`` on the parent Storage resource;
there is no standard Battery resource and no ``StorageController.Links.Batteries``
link. This adds both (synthesizing the Battery resource via a request rewrite, the
same pattern already used for HPE Smart Storage batteries) so the generic
redfish-inventory-exporter ``redfish_storage_battery_*`` metrics work for PERC too.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from redpool.redfish_client import redfish_get_json

from ...._shared.dell_assembly_fru import (
    dell_chassis_path_from_resource_odata_id,
    fetch_chassis_assembly_redpool_fields,
    merge_redpool_assembly_fields,
)
from ....request_rewrites import (
    RequestRewriteRule,
    RewriteCall,
    register_request_rewrite,
)
from ....types import NormalizationContext
from .base import BaseStorageControllerNormalizer

_DELL_SC_ASSEMBLY_FRU = "DellStorageControllerAssemblyFru"


def _parent_storage_path(controller_odata_id: str) -> str:
    """``.../Storage/{sid}/Controllers/{cid}`` -> ``.../Storage/{sid}``."""
    marker = "/Controllers/"
    idx = controller_odata_id.find(marker)
    if idx == -1:
        return ""
    return controller_odata_id[:idx]


def dell_controller_battery(storage_data: Any) -> Optional[Dict[str, Any]]:
    """Return DellControllerBattery dict from Storage Oem.

    iDRAC puts ``DellControllerBattery`` directly under ``Oem.Dell`` (whose
    ``@odata.type`` is often ``DellOemResources``). Older layouts nested it
    under ``Oem.Dell.DellOemResources`` — accept both.
    """
    if not isinstance(storage_data, dict):
        return None
    dell = (storage_data.get("Oem") or {}).get("Dell")
    if not isinstance(dell, dict):
        return None
    battery = dell.get("DellControllerBattery")
    if isinstance(battery, dict) and (
        battery.get("PrimaryStatus") is not None
        or battery.get("RAIDState") is not None
        or battery.get("Name") is not None
        or battery.get("@odata.id") is not None
    ):
        return battery
    resources = dell.get("DellOemResources")
    if isinstance(resources, dict):
        nested = resources.get("DellControllerBattery")
        if isinstance(nested, dict):
            return nested
    return None


def _dell_controller_links(ctx: NormalizationContext) -> Dict[str, Any]:
    links = dict(ctx.data.get("Links") or {})
    battery = ctx.prefetched.get("dell_controller_battery") if ctx.prefetched else None
    if battery:
        links["Batteries"] = [{"@odata.id": f"{ctx.odata_id}/Batteries/1"}]
        links["Batteries@odata.count"] = 1
    return links


def prefetch_dell_storage_controller_assembly_fru(ctx: NormalizationContext) -> None:
    if ctx.client is None:
        return
    parent = _parent_storage_path(ctx.odata_id or "")
    if not parent:
        return
    storage_id = parent.rsplit("/", 1)[-1]
    chassis_path = dell_chassis_path_from_resource_odata_id(parent)
    if not chassis_path:
        return
    fields = fetch_chassis_assembly_redpool_fields(ctx.client, chassis_path, storage_id)
    if not fields:
        return
    if ctx.prefetched is None:
        ctx.prefetched = {}
    ctx.prefetched[_DELL_SC_ASSEMBLY_FRU] = fields


def _dell_storage_controller_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    rp: Dict[str, Any] = (
        dict(out.get("Redpool") or {}) if isinstance(out.get("Redpool"), dict) else {}
    )
    mfg = (ctx.prefetched or {}).get(_DELL_SC_ASSEMBLY_FRU)
    if isinstance(mfg, dict):
        merge_redpool_assembly_fields(rp, mfg)
    if rp:
        out["Redpool"] = rp
    else:
        out.pop("Redpool", None)
    return out


class DellStorageControllerNormalizer(BaseStorageControllerNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        parent = _parent_storage_path(ctx.odata_id)
        if not parent or ctx.client is None:
            return
        storage = redfish_get_json(ctx.client, parent)
        battery = dell_controller_battery(storage)
        if battery:
            ctx.prefetched["dell_controller_battery"] = battery
        prefetch_dell_storage_controller_assembly_fru(ctx)

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Links"] = _dell_controller_links
        m["Oem"] = _dell_storage_controller_oem
        return m


# --- Request rewrite: synthesize .../Controllers/{cid}/Batteries[/1] --------------
# There is no real backend URL for this; fetch the parent Storage resource (which
# already exists) and build the Battery collection/resource from its Oem data.


def _battery_parts(path: str) -> Optional[Tuple[str, List[str]]]:
    marker = "/Controllers/"
    idx = path.find(marker)
    if idx == -1:
        return None
    parent = path[:idx]
    if "/Storage/" not in parent:
        return None
    rest = [p for p in path[idx + len(marker) :].split("/") if p]
    if len(rest) < 2 or rest[1] != "Batteries":
        return None
    return parent, rest


def _dell_batteries_matches(path: str) -> bool:
    return _battery_parts(path) is not None


def _dell_batteries_backend_path(path: str) -> str:
    parsed = _battery_parts(path)
    return parsed[0] if parsed else path


def _dell_batteries_response_rewrite(path: str) -> Tuple[str, str]:
    # after_200_merge builds the exact final body; use a no-op prefix pair so the
    # generic string-rewrite pass does not touch it.
    stripped = path.rstrip("/")
    return stripped, stripped


def _dell_batteries_after_200_merge(call: RewriteCall, body: Any) -> Any:
    path = call.path
    parsed = _battery_parts(path)
    if parsed is None or not isinstance(body, dict):
        return body
    _parent, rest = parsed
    controller_id = rest[0]
    battery = dell_controller_battery(body)
    batteries = [battery] if battery else []
    collection_path = path.rstrip("/")

    if len(rest) == 2:
        members = [
            {"@odata.id": f"{collection_path}/{i + 1}"} for i in range(len(batteries))
        ]
        return {
            "@odata.context": "/redfish/v1/$metadata#BatteryCollection.BatteryCollection",
            "@odata.id": collection_path,
            "@odata.type": "#BatteryCollection.BatteryCollection",
            "Name": "BatteryCollection",
            "Description": "Collection of storage controller batteries",
            "Members": members,
            "Members@odata.count": len(members),
        }

    try:
        index = int(rest[2]) - 1
    except (ValueError, IndexError):
        index = -1
    if index < 0 or index >= len(batteries):
        return {}
    b = batteries[index]
    controller_path = collection_path.rsplit("/Batteries", 1)[0]
    health = b.get("PrimaryStatus")
    return {
        "@odata.context": "/redfish/v1/$metadata#Battery.Battery",
        "@odata.id": collection_path + f"/{index + 1}",
        "@odata.type": "#Battery.v1_5_0.Battery",
        "Id": str(index + 1),
        "Name": b.get("Name") or f"Battery on {controller_id}",
        "Description": b.get("Description"),
        "Manufacturer": None,
        "Status": {
            "Health": health,
            "State": None,
        },
        "Links": {
            "StorageControllers": [{"@odata.id": controller_path}],
            "StorageControllers@odata.count": 1,
        },
        "Oem": {"Dell": {"DellControllerBattery": b}},
    }


register_request_rewrite(
    RequestRewriteRule(
        vendor="Dell",
        matches=_dell_batteries_matches,
        get_backend_path=_dell_batteries_backend_path,
        get_response_rewrite=_dell_batteries_response_rewrite,
        after_200_merge=_dell_batteries_after_200_merge,
    )
)
