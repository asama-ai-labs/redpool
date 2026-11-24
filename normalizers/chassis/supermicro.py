# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Supermicro Chassis: promote Oem.Supermicro.MultiNode into Oem.Redpool."""

from __future__ import annotations

import copy
from typing import Any, Dict, List

from redpool.redfish_client import redfish_get_json

from ..types import NormalizationContext
from .base import BaseChassisNormalizer

_SMC_ASSEMBLY_PRODUCTION_FRU = "SupermicroAssemblyProductionFru"


def prefetch_supermicro_chassis_assembly_fru(ctx: NormalizationContext) -> None:
    """Promote Production FRU Assembly part number from Chassis/Assembly."""
    if ctx.client is None:
        return
    asm = ctx.data.get("Assembly")
    if not isinstance(asm, dict):
        return
    ref = asm.get("@odata.id")
    if not isinstance(ref, str) or not ref.strip():
        return
    try:
        payload = redfish_get_json(ctx.client, ref.strip().split("#", 1)[0])
    except Exception:  # noqa: BLE001
        return
    assemblies = payload.get("Assemblies") if isinstance(payload, dict) else None
    if not isinstance(assemblies, list):
        return
    for block in assemblies:
        if not isinstance(block, dict):
            continue
        name = block.get("Name")
        if isinstance(name, str) and "production" in name.casefold():
            pn = block.get("PartNumber")
            if isinstance(pn, str) and pn.strip():
                if ctx.prefetched is None:
                    ctx.prefetched = {}
                ctx.prefetched[_SMC_ASSEMBLY_PRODUCTION_FRU] = pn.strip()
                return


def _multinode_nodes_link(ctx: NormalizationContext) -> str:
    oem = ctx.data.get("Oem")
    if not isinstance(oem, dict):
        return ""
    smc = oem.get("Supermicro")
    if not isinstance(smc, dict):
        return ""
    mn = smc.get("MultiNode")
    if not isinstance(mn, dict):
        return ""
    nodes = mn.get("Nodes")
    if isinstance(nodes, dict):
        link = nodes.get("@odata.id")
        if isinstance(link, str) and link.strip():
            return link.strip()
    return ""


def _fetch_multinode_nodes(ctx: NormalizationContext) -> List[Dict[str, Any]]:
    """Fetch each member of Oem.Supermicro.MultiNode.Nodes (per-blade health/power)."""
    link = _multinode_nodes_link(ctx)
    if not link or ctx.client is None:
        return []
    try:
        coll = redfish_get_json(ctx.client, link)
    except Exception:  # noqa: BLE001
        return []
    members = coll.get("Members") if isinstance(coll, dict) else None
    if not isinstance(members, list):
        return []
    nodes: List[Dict[str, Any]] = []
    for member in members:
        oid = member.get("@odata.id") if isinstance(member, dict) else None
        if not isinstance(oid, str) or not oid.strip():
            continue
        try:
            node = redfish_get_json(ctx.client, oid)
        except Exception as exc:  # noqa: BLE001
            ctx.logger.error(
                "Error fetching Supermicro MultiNode member %s: %s", oid, exc
            )
            continue
        if isinstance(node, dict) and node:
            nodes.append(node)
    return nodes


def _multinode_node_summary(node: Dict[str, Any]) -> Dict[str, Any]:
    status = node.get("Status") or {}
    summary: Dict[str, Any] = {
        "Id": node.get("Id"),
        "PowerStatus": node.get("PowerStatus"),
        "Health": status.get("Health") if isinstance(status, dict) else None,
        "State": status.get("State") if isinstance(status, dict) else None,
    }
    for key in (
        "BoardPartNumber",
        "BoardSerialNumber",
        "BIOSVersion",
        "CPLDVersion",
        "BMCVersion",
        "DCOutputPower",
        "OutputCurrent",
    ):
        val = node.get(key)
        if val is not None:
            summary[key] = val
    temps = node.get("Temperatures")
    if isinstance(temps, list):
        readings = [
            {"Name": t.get("Name"), "ReadingCelsius": t.get("ReadingCelsius")}
            for t in temps
            if isinstance(t, dict)
            and t.get("Name") is not None
            and t.get("ReadingCelsius") is not None
        ]
        if readings:
            summary["Temperatures"] = readings
    return {k: v for k, v in summary.items() if v is not None}


def _supermicro_chassis_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    src = ctx.data.get("Oem")
    out: Dict[str, Any] = copy.deepcopy(src) if isinstance(src, dict) else {}
    rp: Dict[str, Any] = {}
    existing = out.get("Redpool")
    if isinstance(existing, dict):
        rp = copy.deepcopy(existing)
    smc = out.get("Supermicro")
    if isinstance(smc, dict):
        mn = smc.get("MultiNode")
        if isinstance(mn, dict) and mn:
            # Durable twin/chassis identifiers for inventory join.
            for key in (
                "SystemPartNo",
                "SystemSerialNo",
                "ChassisPartNo",
                "ChassisSerialNo",
                "BackplaneModelName",
                "BackplaneSerialNo",
                "SelfID",
                "TwinType",
                "ConfigurationID",
            ):
                val = mn.get(key)
                if val is None or val == "":
                    continue
                rp[f"MultiNode{key}"] = val
            nodes = mn.get("Nodes")
            if isinstance(nodes, dict) and nodes.get("@odata.id"):
                rp["MultiNodeNodesUri"] = nodes["@odata.id"]
    node_bodies = ctx.prefetched.get("multinode_nodes") if ctx.prefetched else None
    if isinstance(node_bodies, list) and node_bodies:
        rp["MultiNodeNodes"] = [_multinode_node_summary(n) for n in node_bodies]
    production_fru = (
        ctx.prefetched.get(_SMC_ASSEMBLY_PRODUCTION_FRU) if ctx.prefetched else None
    )
    if (
        isinstance(production_fru, str)
        and production_fru.strip()
        and not rp.get("FruPartNumber")
    ):
        rp["FruPartNumber"] = production_fru.strip()
    if rp:
        out["Redpool"] = rp
    else:
        out.pop("Redpool", None)
    return out


class SupermicroChassisNormalizer(BaseChassisNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        super().prefetch(ctx)
        prefetch_supermicro_chassis_assembly_fru(ctx)
        nodes = _fetch_multinode_nodes(ctx)
        if nodes:
            ctx.prefetched["multinode_nodes"] = nodes

    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["Oem"] = _supermicro_chassis_oem
        return m
