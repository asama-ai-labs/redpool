# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Response tweaks for gofish client compatibility.

When enabled via config (normalization.ensure_gofish_compat), the proxy applies
these fixes so clients using gofish (e.g. redfish-inventory-exporter) get correct
data despite gofish using different JSON field names than Redfish in some places.

PCIeFunction ``ClassCode`` canonicalization lives in ``normalizers.pci_class_code``;
see ``normalize_pcie_function_class_code_inplace`` (invoked from the proxy next to
this module's helpers).
"""

from __future__ import annotations

from typing import Any, Dict


def _pcie_function_id_aliases(body: Dict[str, Any]) -> None:
    """Add gofish-style PCI id keys for PCIeFunction (gofish uses DeviceID, VendorID, etc.; Redfish uses DeviceId, VendorId)."""
    if "PCIeFunction" not in (body.get("@odata.type") or ""):
        return
    if "DeviceId" in body and "DeviceID" not in body:
        body["DeviceID"] = body["DeviceId"]
    if "VendorId" in body and "VendorID" not in body:
        body["VendorID"] = body["VendorId"]
    if "SubsystemVendorId" in body and "SubsystemVendorID" not in body:
        body["SubsystemVendorID"] = body["SubsystemVendorId"]
    # Redfish uses "SubsystemId" for subsystem device id; gofish expects "SubsystemDeviceID" or "SubsystemID"
    subsys_src = body.get("SubsystemDeviceId") or body.get("SubsystemId")
    if (
        subsys_src is not None
        and "SubsystemDeviceID" not in body
        and "SubsystemID" not in body
    ):
        body["SubsystemDeviceID"] = subsys_src
        body["SubsystemID"] = subsys_src


def ensure_gofish_compat(body: Any, *, enabled: bool) -> None:
    """Apply all gofish-specific response tweaks in place when enabled.

    Currently: PCIeFunction id field aliases (DeviceID, VendorID, SubsystemVendorID, SubsystemDeviceID/SubsystemID).
    Add further hacks here as needed.
    """
    if not enabled or not isinstance(body, dict):
        return
    _pcie_function_id_aliases(body)
