# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""HPE-specific ComputerSystem normalizer.

Promotes Oem.Hpe.Links.PCIDevices to top-level PCIeDevices (as a Links-style
array) so collectors can discover PCI devices via the standard Redfish path.
The OEM link is left in place.

Also registers a system response expander: expands PCIeDevices from the system's Chassis PCIeDevices
and enriches PCIeFunctions from each device's collection.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from redpool.redfish_client import redfish_get_json

from ..._shared.system_chassis import chassis_from_system_body
from ...optional import OMIT
from ...system_expanders import register_system_response_expander
from ...types import NormalizationContext
from ...url_rewrites import rewrite_odata_id
from .base import BaseComputerSystemNormalizer


def _hpe_pcie_devices(ctx: NormalizationContext) -> Dict[str, Any] | List[Any]:
    """Return PCIeDevices link, promoting HPE OEM PCIDevices when present."""
    standard = ctx.data.get("PCIeDevices")
    if isinstance(standard, dict) and standard.get("@odata.id"):
        return standard
    if isinstance(standard, list) and standard:
        return standard

    hpe_links = (ctx.data.get("Oem") or {}).get("Hpe", {}).get("Links", {})
    pci_devices = hpe_links.get("PCIDevices")
    if isinstance(pci_devices, list) and pci_devices:
        first = pci_devices[0]
        if isinstance(first, dict) and first.get("@odata.id"):
            return [{"@odata.id": rewrite_odata_id(first["@odata.id"])}]
    if isinstance(pci_devices, dict) and pci_devices.get("@odata.id"):
        return [{"@odata.id": rewrite_odata_id(pci_devices["@odata.id"])}]

    return standard if standard is not None else []


def _hpe_system_oem(ctx: NormalizationContext) -> Dict[str, Any]:
    """Return Oem unchanged, plus Oem.Redpool copies of a few HPE labels.

    PCAPartNumber, PostState, and AggregateHealthStatus fields are copied into
    Oem.Redpool for generic collector labels. Oem.Hpe is not rewritten.
    """
    oem = ctx.data.get("Oem") or {}
    oem = copy.deepcopy(oem) if isinstance(oem, dict) else {}

    rp: Dict[str, Any] = (
        dict(oem.get("Redpool") or {}) if isinstance(oem.get("Redpool"), dict) else {}
    )
    hpe = oem.get("Hpe") if isinstance(oem.get("Hpe"), dict) else {}
    pca = hpe.get("PCAPartNumber")
    if isinstance(pca, str) and pca.strip():
        rp["PCAPartNumber"] = pca.strip()
    post = hpe.get("PostState")
    if isinstance(post, str) and post.strip():
        rp["PostState"] = post.strip()
    agg = hpe.get("AggregateHealthStatus")
    if isinstance(agg, dict):
        fr = agg.get("FanRedundancy")
        if isinstance(fr, str) and fr.strip():
            rp["FanRedundancy"] = fr.strip()
        ash = agg.get("AggregateServerHealth")
        if isinstance(ash, str) and ash.strip():
            rp["AggregateServerHealth"] = ash.strip()
    if rp:
        oem["Redpool"] = rp
    return oem


def _hpe_memory_summary(ctx: NormalizationContext) -> Dict[str, Any]:
    """MemorySummary with Status.Health from HealthRollup or the HPE aggregate memory health.

    HPE reports memory health as HealthRollup or as Oem.Hpe.AggregateHealthStatus.Memory.
    No capture gives a memory-specific State, so State is passed through only if the BMC sent it.
    """
    summary = ctx.data.get("MemorySummary")
    if not isinstance(summary, dict):
        return {}
    out = copy.deepcopy(summary)
    status = out.get("Status")
    status = dict(status) if isinstance(status, dict) else {}
    if not status.get("Health"):
        agg = ((ctx.data.get("Oem") or {}).get("Hpe") or {}).get(
            "AggregateHealthStatus"
        )
        memory = agg.get("Memory") if isinstance(agg, dict) else None
        mem_status = memory.get("Status") if isinstance(memory, dict) else None
        health = (
            (mem_status or {}).get("Health") if isinstance(mem_status, dict) else None
        )
        health = health or status.get("HealthRollup")
        if health:
            status["Health"] = health
    if status:
        out["Status"] = status
    return out


class HPEComputerSystemNormalizer(BaseComputerSystemNormalizer):
    """ComputerSystem normalizer for HPE; promotes PCIDevices from Oem to top-level."""

    def field_map(self) -> Dict[str, Any]:
        base = super().field_map()
        return {
            **base,
            "PCIeDevices": _hpe_pcie_devices,
            "HostWatchdogTimer": lambda _ctx: OMIT,
            "MemorySummary": _hpe_memory_summary,
            "Oem": _hpe_system_oem,
        }


# -----------------------------------------------------------------------------
# System response expander: PCIeDevices from Chassis + PCIeFunctions enrichment
# -----------------------------------------------------------------------------


def _expand_hpe_system_pcie_devices(
    data: Dict[str, Any],
    path: str,
    client: Any,
) -> Dict[str, Any]:
    """Expand PCIeDevices for HPE systems.

    Preferred source is the system's Chassis PCIeDevices so that we get full PCIeDevice
    resources. When that collection is missing or empty (some HPE models),
    fall back to Systems/1/PCIDevices but expose the canonical
    Systems/1/PCIeDevices/{id} URIs so generic Redfish clients can follow them.
    """
    pcie_devices = data.get("PCIeDevices")
    if not isinstance(pcie_devices, list) or len(pcie_devices) != 1:
        return data
    link = pcie_devices[0]
    if not isinstance(link, dict):
        return data
    odata_id = (link.get("@odata.id") or "").strip()
    if not odata_id.endswith("/PCIeDevices"):
        return data
    if "/Systems/" not in path or path.rstrip("/").count("/") < 3:
        return data
    system_base = odata_id[: -len("/PCIeDevices")]
    chassis = chassis_from_system_body(data) or "/redfish/v1/Chassis/1"
    chassis_prefix = f"{chassis}/PCIeDevices"
    systems_prefix = f"{system_base}/PCIeDevices"
    chassis_coll = redfish_get_json(client, chassis_prefix)

    chassis_links: list[Dict[str, Any]] = []
    if chassis_coll:
        coll = chassis_coll
        for m in coll.get("Members") or []:
            odata = (m.get("@odata.id") or "").strip() if isinstance(m, dict) else ""
            if odata:
                chassis_links.append(
                    {"@odata.id": odata.replace(chassis_prefix, systems_prefix)}
                )

    if chassis_links:
        data = dict(data)
        data["PCIeDevices"] = chassis_links
        return data

    # Fallback: Chassis PCIeDevices missing, empty, or members lack @odata.id
    # (some iLO firmware returns blank @odata.id).  Use Systems/PCIDevices instead.
    pcidev_path = system_base.rstrip("/") + "/PCIDevices"
    pcidev_coll = redfish_get_json(client, pcidev_path)
    members: list[Dict[str, Any]] = []
    if pcidev_coll:
        members = pcidev_coll.get("Members") or []

    if not members:
        return data

    data = dict(data)
    # Group backend PCIDevices by physical device so multi-function cards
    # appear as a single PCIeDevice (the collector sees function_count > 1).
    from normalizers.systems.pci_devices.hpe import get_hpe_pcidevice_grouping

    pcidev_path = system_base.rstrip("/") + "/PCIDevices"
    grouping = get_hpe_pcidevice_grouping(client, pcidev_path)
    if grouping:
        pcie_links = [
            {"@odata.id": f"{systems_prefix}/{gid}"}
            for gid in sorted(
                grouping, key=lambda i: (int(i) if i.isdigit() else 999, i)
            )
        ]
    else:
        pcie_links = []
        for m in members:
            if not isinstance(m, dict):
                continue
            member_id = (m.get("@odata.id") or "").rstrip("/").split("/")[-1]
            if member_id:
                pcie_links.append({"@odata.id": f"{systems_prefix}/{member_id}"})
    if not pcie_links:
        return data
    data["PCIeDevices"] = pcie_links
    return data


def _enrich_hpe_system_pcie_functions(
    data: Dict[str, Any],
    path: str,
    client: Any,
    *,
    proxy_request: Optional[Any] = None,
    backend_client: Optional[Any] = None,
    server_metadata: Optional[Any] = None,
) -> Dict[str, Any]:
    """Populate ComputerSystem.PCIeFunctions from each PCIeDevice's PCIeFunctions collection."""
    if "/Systems/" not in path:
        return data
    suffix = path.rstrip("/").split("/Systems/")[-1]
    if "/" in suffix:
        return data
    pcie_devices = data.get("PCIeDevices")
    if not isinstance(pcie_devices, list) or len(pcie_devices) == 0:
        return data
    all_links: List[Dict[str, str]] = []
    for item in pcie_devices:
        if not isinstance(item, dict):
            continue
        odata_id = (item.get("@odata.id") or "").rstrip("/")
        if not odata_id:
            continue
        pcie_functions_path = odata_id + "/PCIeFunctions"
        coll: Optional[Dict[str, Any]] = None
        if (
            proxy_request is not None
            and backend_client is not None
            and server_metadata is not None
        ):
            coll, _, status, *_ = proxy_request(
                path=pcie_functions_path,
                method="GET",
                backend_client=backend_client,
                server_metadata=server_metadata,
            )
            if status != 200:
                coll = None
        else:
            coll = redfish_get_json(client, pcie_functions_path)
        if isinstance(coll, dict):
            for m in coll.get("Members") or []:
                if isinstance(m, dict) and m.get("@odata.id"):
                    all_links.append({"@odata.id": m["@odata.id"]})
    if not all_links:
        return data
    out = dict(data)
    out["PCIeFunctions"] = all_links
    out["PCIeFunctions@odata.count"] = len(all_links)
    return out


def expand_system_response_hpe(
    data: Dict[str, Any],
    path: str,
    client: Any,
    *,
    proxy_request: Optional[Any] = None,
    backend_client: Optional[Any] = None,
    server_metadata: Optional[Any] = None,
) -> Dict[str, Any]:
    """HPE system response expander: expand PCIeDevices from Chassis, then enrich PCIeFunctions."""
    data = _expand_hpe_system_pcie_devices(data, path, client)
    data = _enrich_hpe_system_pcie_functions(
        data,
        path,
        client,
        proxy_request=proxy_request,
        backend_client=backend_client,
        server_metadata=server_metadata,
    )
    return data


# Register so the proxy can look up by vendor
register_system_response_expander("HPE", expand_system_response_hpe)
