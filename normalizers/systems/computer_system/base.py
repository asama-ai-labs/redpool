# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base ComputerSystem normalizer.

Vendor-specific behavior (e.g. HPE promoting Oem.Hpe.Links.PCIDevices to
top-level PCIeDevices) lives in vendor modules; see hpe.py.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from redpool.redfish_client import redfish_get_json

from ...base import ResourceNormalizer
from normalizers._shared.status_fields import (
    adapter_status_needs_pcie_fill,
    status_field_unknown_or_empty,
)
from ..._shared.system_chassis import chassis_from_system_body
from ...optional import optional
from ...types import NormalizationContext


def _pcie_devices(ctx: NormalizationContext) -> Dict[str, Any] | List[Any]:
    """Return PCIeDevices from payload; vendor overrides may promote OEM links.
    When the system has no top-level PCIeDevices but has Links.Chassis, use the
    first chassis PCIeDevices link so collectors that only read system.PCIeDevices()
    still see chassis-attached PCIe devices (e.g. Supermicro).
    """
    standard = ctx.data.get("PCIeDevices")
    if standard is not None:
        if isinstance(standard, dict) and standard.get("@odata.id"):
            return standard
        if isinstance(standard, list) and standard:
            return standard
    # Fallback: point to first chassis PCIeDevices so system.PCIeDevices() works
    chassis = chassis_from_system_body(ctx.data)
    if chassis:
        # gofish expects PCIeDevices as Links (array of link objects)
        return [{"@odata.id": f"{chassis}/PCIeDevices"}]
    return []


def _oem(ctx: NormalizationContext) -> Dict[str, Any]:
    """Return Oem from payload; vendor overrides may strip promoted links."""
    return ctx.data.get("Oem") or {}


def _bios_link(ctx: NormalizationContext) -> Any:
    """Return Bios link as an object { \"@odata.id\": url } so gofish's common.Link unmarshals correctly.
    Rewrite lowercase path segments to canonical (Systems, Bios) for BMCs that use wrong case.
    """
    raw = ctx.data.get("Bios")
    odata_id: str | None = None
    if isinstance(raw, str) and raw.strip():
        odata_id = raw.strip()
    elif isinstance(raw, dict):
        odata_id = (
            raw.get("@odata.id") if isinstance(raw.get("@odata.id"), str) else None
        )
    if not odata_id:
        return raw if isinstance(raw, dict) else None
    # Canonical Redfish uses /redfish/v1/Systems/.../Bios (gofish Link expects object, not string)
    out = odata_id.replace("/systems/", "/Systems/").replace("/bios", "/Bios")
    return {"@odata.id": out}


def _processors_collection_odata_id(ctx: NormalizationContext) -> Optional[str]:
    link = ctx.data.get("Processors")
    if isinstance(link, dict):
        oid = link.get("@odata.id")
        if isinstance(oid, str) and oid.strip():
            return oid.strip()
    base = ctx.odata_id
    if isinstance(base, str) and base.strip():
        return f"{base.rstrip('/')}/Processors"
    return None


def _processor_summary_needs_cpu_status_fill(data: Dict[str, Any]) -> bool:
    proc_sum = data.get("ProcessorSummary")
    if proc_sum is None:
        return True
    if not isinstance(proc_sum, dict):
        return False
    return adapter_status_needs_pcie_fill(proc_sum.get("Status"))


def _is_cpu_processor(body: Dict[str, Any]) -> bool:
    ptype = body.get("ProcessorType")
    if ptype is None:
        return True
    if isinstance(ptype, str) and not ptype.strip():
        return True
    return str(ptype).strip().casefold() == "cpu"


def _effective_health_from_status(st: Any) -> Optional[str]:
    if not isinstance(st, dict):
        return None
    h = st.get("Health")
    if isinstance(h, str) and h.strip() and h.strip().casefold() != "unknown":
        return h.strip()
    hr = st.get("HealthRollup")
    if isinstance(hr, str) and hr.strip() and hr.strip().casefold() != "unknown":
        return hr.strip()
    return None


def _state_from_status(st: Any) -> Optional[str]:
    if not isinstance(st, dict):
        return None
    s = st.get("State")
    if isinstance(s, str) and s.strip() and s.strip().casefold() != "unknown":
        return s.strip()
    return None


def _health_severity_rank(health: str) -> int:
    key = health.strip().casefold()
    if key == "critical":
        return 4
    if key in ("warning", "minor"):
        return 3
    if key == "ok":
        return 2
    if key == "unknown":
        return 1
    return 1


def _worst_health_value(healths: List[Optional[str]]) -> Optional[str]:
    best_rank = -1
    chosen: Optional[str] = None
    for h in healths:
        if h is None:
            continue
        s = str(h).strip()
        if not s:
            continue
        r = _health_severity_rank(s)
        if r > best_rank:
            best_rank = r
            chosen = s
    return chosen


def _rollup_processor_states(states: List[Optional[str]]) -> Optional[str]:
    concrete = [
        s
        for s in states
        if s is not None and str(s).strip() and str(s).strip().casefold() != "unknown"
    ]
    if not concrete:
        return None
    if len({s.casefold() for s in concrete}) == 1:
        return concrete[0]
    # Mixed states have no single Status.State, so the property is omitted.
    return None


def _processor_summary(ctx: NormalizationContext) -> Dict[str, Any]:
    raw = ctx.data.get("ProcessorSummary")
    out: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    synth = ctx.prefetched.get("processor_summary_status")
    if not isinstance(synth, dict) or not synth:
        return out
    st = dict(out["Status"]) if isinstance(out.get("Status"), dict) else {}
    for key, val in synth.items():
        if val is None:
            continue
        if status_field_unknown_or_empty(st.get(key)):
            st[key] = val
    out["Status"] = st
    return out


class BaseComputerSystemNormalizer(ResourceNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        if ctx.config and not ctx.config.build_processor_summary_status:
            return
        if not ctx.client:
            return
        if not _processor_summary_needs_cpu_status_fill(ctx.data):
            return
        coll_id = _processors_collection_odata_id(ctx)
        if not coll_id:
            return
        try:
            coll = redfish_get_json(ctx.client, coll_id)
            members = coll.get("Members")
            if not isinstance(members, list):
                return
            health_inputs: List[Optional[str]] = []
            state_inputs: List[Optional[str]] = []
            for ref in members:
                if not isinstance(ref, dict):
                    continue
                oid = ref.get("@odata.id")
                if not isinstance(oid, str):
                    continue
                body = redfish_get_json(ctx.client, oid)
                if (
                    not body
                    or not isinstance(body, dict)
                    or not _is_cpu_processor(body)
                ):
                    continue
                pst = body.get("Status")
                health_inputs.append(_effective_health_from_status(pst))
                state_inputs.append(_state_from_status(pst))
            worst_h = _worst_health_value(health_inputs)
            state_r = _rollup_processor_states(state_inputs)
            synth: Dict[str, Any] = {}
            if worst_h is not None:
                synth["Health"] = worst_h
                synth["HealthRollup"] = worst_h
            if state_r is not None:
                synth["State"] = state_r
            if not synth:
                return
            ctx.prefetched["processor_summary_status"] = synth
        except Exception as exc:
            ctx.logger.error("Error prefetching processor summary status: %s", exc)

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#ComputerSystem.ComputerSystem",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#ComputerSystem.v1_25_0.ComputerSystem",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
            "Description": optional("Description"),
            "SystemType": optional("SystemType"),
            "Manufacturer": optional("Manufacturer"),
            "Model": optional("Model"),
            "SubModel": lambda ctx: ctx.data.get("SubModel") or "",
            "SerialNumber": optional("SerialNumber"),
            "PartNumber": optional("PartNumber"),
            "SKU": optional("SKU"),
            "UUID": optional("UUID"),
            "AssetTag": optional("AssetTag"),
            "HostName": optional("HostName"),
            "BiosVersion": optional("BiosVersion"),
            "PowerState": optional("PowerState"),
            "IndicatorLED": optional("IndicatorLED"),
            "LocationIndicatorActive": optional("LocationIndicatorActive"),
            "Boot": lambda ctx: ctx.data.get("Boot", {}),
            "BootProgress": lambda ctx: ctx.data.get("BootProgress", {}),
            "ProcessorSummary": _processor_summary,
            "MemorySummary": lambda ctx: ctx.data.get("MemorySummary", {}),
            "TrustedModules": lambda ctx: ctx.data.get("TrustedModules", []),
            "HostWatchdogTimer": optional("HostWatchdogTimer"),
            "HostingRoles": lambda ctx: ctx.data.get("HostingRoles", []),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Actions": lambda ctx: ctx.data.get("Actions", {}),
            "Bios": _bios_link,
            "Processors": lambda ctx: ctx.data.get("Processors", {}),
            "Memory": lambda ctx: ctx.data.get("Memory", {}),
            "EthernetInterfaces": lambda ctx: ctx.data.get("EthernetInterfaces", {}),
            "Storage": lambda ctx: ctx.data.get("Storage", {}),
            "SimpleStorage": lambda ctx: ctx.data.get("SimpleStorage", {}),
            "NetworkInterfaces": lambda ctx: ctx.data.get("NetworkInterfaces", {}),
            "SecureBoot": lambda ctx: ctx.data.get("SecureBoot", {}),
            "VirtualMedia": lambda ctx: ctx.data.get("VirtualMedia", {}),
            "PCIeDevices": _pcie_devices,
            "PCIeFunctions": lambda ctx: ctx.data.get("PCIeFunctions", []),
            "LogServices": lambda ctx: ctx.data.get("LogServices", {}),
            "GraphicalConsole": lambda ctx: ctx.data.get("GraphicalConsole", {}),
            "Oem": _oem,
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#ComputerSystemCollection.ComputerSystemCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#ComputerSystemCollection.ComputerSystemCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of Computer Systems",
    "Name": "Computer System Collection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
