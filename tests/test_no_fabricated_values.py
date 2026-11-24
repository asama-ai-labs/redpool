# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Normalized output never states a value the BMC did not send.

When the raw payload lacks a property, the normalizer leaves it null or omits it.
It must not use a plausible default: an HPE or Dell maker name, ``Enabled``,
``LinkDown``, ``Ethernet``, ``0x0000``, ``SingleFunction`` or ``Physical``.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from normalizers.chassis.drives.base import _drive_manufacturer
from normalizers.chassis.network_adapters.hpe_chassis_network_rewrite import (
    _physical_to_port,
)
from normalizers.chassis.power_supplies.base import _power_supply_manufacturer
from normalizers.systems.pci_devices.base import _device_type
from normalizers.systems.pci_devices.hpe import (
    build_synthetic_pcie_function_from_pcidevice,
)
from normalizers.systems.storage._hpe_smartstorage import (
    build_drive_resource,
    build_storage_controller_resource,
)
from normalizers.types import NormalizationContext

NORMALIZERS_DIR = Path(__file__).resolve().parents[1] / "normalizers"


def _ctx(data: dict, **kwargs) -> NormalizationContext:
    return NormalizationContext(
        data=data,
        client=None,
        logger=logging.getLogger("test"),
        **kwargs,
    )


# --- SmartStorage drive and controller ------------------------------------------------


def test_drive_has_no_invented_failure_prediction_or_duplicate_speed() -> None:
    out = build_drive_resource(
        "/redfish/v1/Systems/1/Storage/1/Drives/1",
        {"Id": "1", "InterfaceSpeedMbps": 12000},
    )
    assert out["FailurePredicted"] is None
    assert out["CapableSpeedGbs"] is None
    assert out["NegotiatedSpeedGbs"] == 12


def test_storage_controller_manufacturer_is_not_assumed_hpe() -> None:
    out = build_storage_controller_resource(
        "/redfish/v1/Systems/1/Storage/1", {"Id": "1", "Model": "P408i-a"}
    )
    assert out["Manufacturer"] is None


# --- Network ports ---------------------------------------------------------------------


def test_physical_port_without_state_or_link_technology_is_null() -> None:
    out = _physical_to_port({"Name": "Port 1"}, "/redfish/v1/x/Ports/1", 1)
    assert out["Status"] == {"State": None}
    assert "LinkNetworkTechnology" not in out
    assert "LinkStatus" not in out


# --- PCIe ---------------------------------------------------------------------------


def test_pcie_function_without_ids_or_class_invents_nothing() -> None:
    out = build_synthetic_pcie_function_from_pcidevice(
        {"Name": "NIC"},
        "/redfish/v1/Systems/1/PCIeDevices/1/PCIeFunctions/1",
        "/redfish/v1/Systems/1/PCIeDevices/1",
    )
    assert out["VendorId"] is None
    assert out["DeviceId"] is None
    assert out["SubsystemId"] is None
    assert out["SubsystemVendorId"] is None
    assert out["ClassCode"] is None
    assert "DeviceClass" not in out
    assert "FunctionType" not in out
    assert out["FunctionId"] is None


def test_pcie_function_uses_bmc_function_number() -> None:
    out = build_synthetic_pcie_function_from_pcidevice(
        {"Name": "NIC", "FunctionNumber": 2},
        "/redfish/v1/x/PCIeFunctions/2",
        "/redfish/v1/x",
        function_index=1,
    )
    assert out["FunctionId"] == 2


def test_hpe_pcie_device_type_is_not_guessed_as_single_function() -> None:
    ctx = _ctx({"@odata.type": "#HpeServerPciDevice.v1_0_0.HpeServerPciDevice"})
    assert _device_type(ctx) is None


# --- Manufacturer fallbacks: the server vendor is not a component's maker -------------


def test_power_supply_manufacturer_is_not_the_server_vendor() -> None:
    assert _power_supply_manufacturer(_ctx({}, vendor="Dell")) is None


def test_drive_manufacturer_is_not_the_server_vendor() -> None:
    assert _drive_manufacturer(_ctx({}, vendor="HPE")) is None


# --- Static guard -----------------------------------------------------------------------

# Keys whose literal values are, in every case, a claim about the hardware.
_CLAIM_KEYS_STR = frozenset(
    {
        "Manufacturer",
        "State",
        "Health",
        "LinkStatus",
        "ActiveLinkTechnology",
        "LinkNetworkTechnology",
        "FunctionType",
        "DeviceClass",
        "DeviceType",
    }
)
_CLAIM_KEYS_BOOL = frozenset({"FailurePredicted"})
_PCI_ID_KEYS = frozenset(
    {"VendorId", "DeviceId", "SubsystemId", "SubsystemVendorId", "ClassCode"}
)

# (relative path, key) pairs reviewed as legitimate constants. Keep this short, and
# give a reason for every entry.
_ALLOWLIST: dict[tuple[str, str], str] = {}


def _literal_claims(tree: ast.AST):
    """Yield (key, value, lineno) for literal claim values in dict displays and subscripts."""

    def claim(key: str, value: ast.AST) -> bool:
        if not isinstance(value, ast.Constant):
            return False
        v = value.value
        if key in _CLAIM_KEYS_BOOL:
            return isinstance(v, bool)
        if key in _CLAIM_KEYS_STR:
            return isinstance(v, str) and bool(v.strip())
        if key in _PCI_ID_KEYS:
            return isinstance(v, str) and v.lower().startswith("0x")
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    if claim(k.value, v):
                        yield k.value, v.value, v.lineno
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                    and claim(target.slice.value, node.value)
                ):
                    yield target.slice.value, node.value.value, node.lineno


def test_normalizers_do_not_assign_literal_hardware_claims() -> None:
    violations = []
    for path in sorted(NORMALIZERS_DIR.rglob("*.py")):
        rel = str(path.relative_to(NORMALIZERS_DIR))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for key, value, line in _literal_claims(tree):
            if (rel, key) in _ALLOWLIST:
                continue
            violations.append(f"{rel}:{line}: {key!r} = {value!r}")
    assert not violations, (
        "Normalizers state literal hardware claims. Copy the value from the payload, "
        "leave it null or omit it, or add a reviewed allowlist entry:\n"
        + "\n".join(violations)
    )
