# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Vendor keys are canonicalized, so every spelling a BMC sends reaches the same normalizer."""

import pytest

import normalizers  # noqa: F401  registers every resource
from normalizers.base import ResourceNormalizer
from normalizers.registry import (
    NormalizerEntry,
    _registry,
    get_collection_mapping,
    get_resource_entry,
    register_base,
    register_collection_override,
    register_resource,
)
from normalizers.request_rewrites import get_request_rewrite
from normalizers.vendor_id import canonical_server_vendor


@pytest.mark.parametrize(
    "raw, canonical",
    [
        ("Dell", "Dell"),
        ("Dell Inc.", "Dell"),
        (" dell inc. ", "Dell"),
        ("HPE", "HPE"),
        ("Hpe", "HPE"),
        ("Hewlett Packard Enterprise", "HPE"),
        ("Lenovo", "Lenovo"),
        ("Supermicro", "Supermicro"),
        ("Super Micro Computer, Inc.", "Supermicro"),
        ("Intel", "Intel"),
        ("Intel Corporation", "Intel"),
        ("Acme", "Acme"),
        ("", ""),
        (None, ""),
    ],
)
def test_canonical_server_vendor(raw, canonical):
    assert canonical_server_vendor(raw) == canonical


@pytest.mark.parametrize("spelling", ["Dell", "Dell Inc.", "DELL", "dell inc."])
def test_every_dell_spelling_gets_the_dell_normalizer(spelling):
    entry = get_resource_entry("Systems")
    assert entry is not None
    assert entry.for_vendor(spelling) is entry.vendors["Dell"]


def test_intel_corporation_reaches_the_intel_normalizer():
    # ServiceRoot.Vendor is "Intel Corporation"; the normalizers register as "Intel".
    entry = get_resource_entry("Systems/Processors")
    assert entry is not None
    assert entry.for_vendor("Intel Corporation") is entry.vendors["Intel"]


def test_hpe_oem_key_fallback_reaches_the_hpe_normalizer():
    # With no ServiceRoot.Vendor the proxy uses the first Oem key, which is "Hpe".
    entry = get_resource_entry("Systems")
    assert entry is not None
    assert entry.for_vendor("Hpe") is entry.vendors["HPE"]


def test_unknown_vendor_falls_back_to_base():
    entry = get_resource_entry("Systems")
    assert entry is not None
    assert entry.for_vendor("Acme") is entry.base
    assert entry.for_vendor("unknown") is entry.base


def test_register_resource_canonicalizes_the_key_and_rejects_a_different_class():
    class A(ResourceNormalizer):
        def field_map(self):
            return {}

    class B(ResourceNormalizer):
        def field_map(self):
            return {}

    pattern = "TestOnly/Vendors"
    register_base(pattern, A())
    try:
        register_resource(pattern, "Dell Inc.", A())
        entry = get_resource_entry(pattern)
        assert isinstance(entry, NormalizerEntry)
        assert list(entry.vendors) == ["Dell"]
        register_resource(pattern, "Dell", A())  # same class: fine
        with pytest.raises(ValueError, match="already has a Dell normalizer"):
            register_resource(pattern, "Dell", B())
    finally:
        _registry.pop(pattern, None)


def test_request_rewrite_matches_any_spelling_of_the_vendor():
    path = "/redfish/v1/Chassis/1/NetworkAdapters/x/NetworkPorts"
    for spelling in ("HPE", "Hpe", "Hewlett Packard Enterprise"):
        assert get_request_rewrite(spelling, path) is not None, spelling
    assert get_request_rewrite("Acme", path) is None


def test_collection_override_is_chosen_by_canonical_vendor():
    mapping = get_collection_mapping("UpdateService/FirmwareInventory")
    assert mapping is not None
    dell = mapping.for_vendor("Dell Inc.")
    assert dell is mapping.vendors["Dell"]
    assert dell is not mapping
    assert mapping.for_vendor("Lenovo") is mapping


def test_dell_firmware_collection_keeps_id_only_members_as_links():
    from normalizers import NormalizationContext, evaluate

    members = [
        {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/A", "Id": "A"},
        {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/B", "Name": "B"},
    ]
    mapping = get_collection_mapping("UpdateService/FirmwareInventory")
    assert mapping is not None
    ctx = NormalizationContext(
        data={"Members": members}, client=None, logger=None, config={}, vendor="Dell"
    )
    dell = evaluate(mapping.for_vendor("Dell"), ctx)["Members"]
    other = evaluate(mapping.for_vendor("Lenovo"), ctx)["Members"]
    assert dell[0] == {"@odata.id": "/redfish/v1/UpdateService/FirmwareInventory/A"}
    assert dell[1] == members[1]
    assert other == members


def test_register_collection_override_needs_a_base_mapping():
    with pytest.raises(ValueError, match="No collection mapping registered"):
        register_collection_override("TestOnly/Missing", "Dell", {})


def test_system_expander_is_found_under_any_spelling_of_the_vendor():
    from normalizers.system_expanders import get_system_response_expander

    expander = get_system_response_expander("HPE")
    assert expander is not None
    assert get_system_response_expander("Hpe") is expander
    assert get_system_response_expander("Dell") is None
