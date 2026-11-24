# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Normalizer output stays inside the pinned DMTF schemas: enums, versions, deprecations."""

from __future__ import annotations

import json
import logging

import pytest

from normalizers.chassis.drives.base import BaseChassisDriveNormalizer
from normalizers.evaluator import evaluate
from normalizers.systems.computer_system.base import _rollup_processor_states
from normalizers.systems.memory.hpe import map_hpe_dimm_status
from normalizers.systems.pci_devices.base import (
    _CLASS_CODE_MAP,
    device_class_from_pci_class,
)
from normalizers.types import NormalizationContext
from redpool.schema_validator import (
    deprecation_notes,
    is_dmtf_type_newer_than_bundle,
    schema_bundle_available,
    schema_dir,
)

needs_bundle = pytest.mark.skipif(
    not schema_bundle_available(),
    reason="Redfish-Publications submodule not checked out",
)


def _device_class_enum() -> list[str]:
    files = sorted(schema_dir().glob("PCIeFunction.v1_*.json"))
    return json.loads(files[-1].read_text())["definitions"]["DeviceClass"]["enum"]


def test_pci_class_codes_from_the_pci_specification() -> None:
    assert device_class_from_pci_class(0x10) == "EncryptionController"
    assert device_class_from_pci_class(0x12) == "ProcessingAccelerators"
    assert device_class_from_pci_class(0x40) == "Coprocessor"
    assert device_class_from_pci_class(0xFF) == "UnassignedClass"
    # A code with no DMTF name is Other, never an invented value.
    assert device_class_from_pci_class(0x77) == "Other"


@needs_bundle
def test_every_pci_class_value_is_in_the_dmtf_enum() -> None:
    allowed = set(_device_class_enum())
    bad = {v for v in _CLASS_CODE_MAP.values() if v not in allowed}
    assert not bad, f"not DMTF DeviceClass values: {sorted(bad)}"


def test_mixed_processor_states_omit_state() -> None:
    assert _rollup_processor_states(["Enabled", "Disabled"]) is None


def test_agreeing_processor_states_keep_state() -> None:
    assert _rollup_processor_states(["Enabled", "Enabled", "Unknown"]) == "Enabled"


def test_hpe_dimm_status_unknown_is_not_mapped() -> None:
    assert map_hpe_dimm_status("Unknown") is None
    assert map_hpe_dimm_status("GoodInUse") == {
        "Health": "OK",
        "State": "Enabled",
        "HealthRollup": "OK",
    }


def _drive(data: dict) -> dict:
    ctx = NormalizationContext(data=data, client=None, logger=logging.getLogger("t"))
    return evaluate(BaseChassisDriveNormalizer().field_map(), ctx)


def test_drive_location_is_emitted_only_when_the_bmc_sent_it() -> None:
    assert "Location" not in _drive({"Id": "1"})
    assert _drive({"Id": "1", "Location": []})["Location"] == []


@needs_bundle
def test_newer_dmtf_version_is_detected() -> None:
    assert is_dmtf_type_newer_than_bundle("#Port.v1_99_0.Port") is True
    assert is_dmtf_type_newer_than_bundle("#Port.v1_20_0.Port") is False


@needs_bundle
def test_oem_and_odd_types_are_not_flagged_as_newer() -> None:
    assert is_dmtf_type_newer_than_bundle("#HpeBaseNetworkAdapter.v2_0_0.X") is False
    assert is_dmtf_type_newer_than_bundle("#Redpool.v1_0_0.RedpoolChassis") is False
    assert is_dmtf_type_newer_than_bundle(None) is False
    assert is_dmtf_type_newer_than_bundle("Port") is False


@needs_bundle
def test_deprecated_schema_and_property_are_reported() -> None:
    power = {"@odata.type": "#Power.v1_7_3.Power", "Id": "Power"}
    assert "type:#Power.v1_7_3.Power" in deprecation_notes(power)
    drive = {"@odata.type": "#Drive.v1_19_0.Drive", "Location": []}
    assert "property:Drive.Location" in deprecation_notes(drive)
    assert deprecation_notes({"@odata.type": "#Drive.v1_19_0.Drive"}) == []
    assert deprecation_notes("not a dict") == []
