# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

import tempfile
from unittest.mock import MagicMock, patch

import pytest

from redfish_snapshot.main import RedfishCloner
from redfish_snapshot.sanitize import (
    build_dirgroup_id_map,
    sanitize_redfish,
    sanitize_resource_tokens,
)


@pytest.fixture
def cloner():
    with tempfile.TemporaryDirectory() as td:
        with patch("redfish_snapshot.main.HttpClient") as mock_http:
            mock_http.return_value = MagicMock()
            yield RedfishCloner(
                host="127.0.0.1",
                username="u",
                password="p",
                output_path=td,
                sanitize=True,
            )


def test_firmware_version_not_masked_as_ipv4(cloner):
    out = cloner.sanitize_data({"FirmwareVersion": "2.85.85.85"})
    assert out["FirmwareVersion"] == "2.85.85.85"


def test_firmware_package_version_not_masked_as_ipv4(cloner):
    out = cloner.sanitize_data(
        {
            "Controllers": [{"FirmwarePackageVersion": "222.1.73.0"}],
            "Message": "see 10.0.0.1",
        }
    )
    assert out["Controllers"][0]["FirmwarePackageVersion"] == "222.1.73.0"
    assert out["Message"] == "see 192.0.2.1"


def test_plain_field_still_masks_ipv4(cloner):
    out = cloner.sanitize_data({"Message": "see 10.0.0.1"})
    assert out["Message"] == "see 192.0.2.1"


def test_firmware_inventory_odata_id_preserved(cloner):
    uri = "/redfish/v1/UpdateService/FirmwareInventory/Installed-25227-2.85.85.85"
    out = cloner.sanitize_data({"@odata.id": uri})
    assert out["@odata.id"] == uri


def test_firmware_inventory_odata_id_slot_suffix_preserved(cloner):
    uri = (
        "/redfish/v1/UpdateService/FirmwareInventory/"
        "Installed-25227-7.10.30.00__iDRAC.Embedded.1-1"
    )
    out = cloner.sanitize_data({"@odata.id": uri})
    assert out["@odata.id"] == uri


def test_software_inventory_version_preserved(cloner):
    out = cloner.sanitize_data(
        {
            "@odata.type": "#SoftwareInventory.v1_1_1.SoftwareInventory",
            "Version": "7.10.30.00",
        }
    )
    assert out["Version"] == "7.10.30.00"


def test_bios_attribute_system_me_version_preserved(cloner):
    out = cloner.sanitize_data(
        {
            "Attributes": {
                "SystemMeVersion": "4.0.4.188",
            }
        }
    )
    assert out["Attributes"]["SystemMeVersion"] == "4.0.4.188"


def test_message_args_still_masks_ipv4(cloner):
    out = cloner.sanitize_data({"MessageArgs": ["10.0.0.1"]})
    assert out["MessageArgs"] == ["192.0.2.1"]


def test_masks_email_and_mailto(cloner):
    out = cloner.sanitize_data(
        {
            "Note": "contact a@b.co ok",
            "Dest": "mailto:alerts@relay.untrusted",
        }
    )
    assert "DUMMY@example.invalid" in out["Note"]
    assert out["Dest"].startswith("mailto:")
    assert "untrusted" not in out["Dest"].lower()


def test_masks_untrusted_fqdns_preserves_allowlisted_hosts(cloner):
    out = cloner.sanitize_data(
        {
            "SmtpHost": "mail.relay.customer.test",
            "SchemaUri": "http://redfish.dmtf.org/schemas/v1/AccountService.json",
        }
    )
    assert out["SmtpHost"] == cloner.DUMMY_FQDN
    assert "dmtf.org" in out["SchemaUri"]
    assert "customer" not in out["SmtpHost"].lower()


def test_fqdn_mask_skips_pascalcase_redfish_type_fragments(cloner):
    out = cloner.sanitize_data(
        {
            "Type": "#EventService.v1_10_0.EventService",
            "Host": "mail.relay.customer.test",
        }
    )
    assert out["Type"] == "#EventService.v1_10_0.EventService"
    assert out["Host"] == cloner.DUMMY_FQDN


def test_preserves_ssh_algo_at_domain(cloner):
    out = cloner.sanitize_data({"Cipher": "chacha20-poly1305@openssh.com"})
    assert out["Cipher"] == "chacha20-poly1305@openssh.com"


def test_replaces_pem_block(cloner):
    pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\ntrail"
    out = cloner.sanitize_data({"CertificateString": pem})
    assert "BEGIN CERTIFICATE" in out["CertificateString"]
    assert "DUMMY-PEM-REDACTED" in out["CertificateString"]
    assert "MIIB" not in out["CertificateString"]


def test_masks_uuid_tokens(cloner):
    u = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    out = cloner.sanitize_data({"Id": u, "Text": f"prefix {u} suffix"})
    # One placeholder per distinct UUID, the same one wherever that UUID appears.
    assert out["Id"].startswith(cloner.DUMMY_UUID[:24])
    assert out["Id"] in out["Text"]
    assert "aaaaaaa" not in out["Text"]


def test_mac_in_associated_network_addresses_list(cloner):
    out = cloner.sanitize_data({"AssociatedNetworkAddresses": ["00:1B:44:AA:BB:CC"]})
    assert out["AssociatedNetworkAddresses"] == [cloner.DUMMY_MAC]


def test_subject_common_name_asset_redacted(cloner):
    out = cloner.sanitize_data(
        {
            "Subject": {
                "Country": "US",
                "CommonName": "XCC-7Z73-J30AB503",
            }
        }
    )
    assert out["Subject"]["CommonName"] == cloner.DUMMY_COMMON_NAME
    assert out["Subject"]["Country"] == "US"


def test_dotted_attribute_leaves(cloner):
    out = cloner.sanitize_data(
        {
            "Users.2.UserName": "root",
            "Users.2.LoginID": "maas",
            "Users.2.Password": "None",
            "Users.2.SHA256Password": "secret-hash",
            "Users.2.SHA256PasswordSalt": "secret-salt",
            "Users.2.IPMIKey": "secret-ipmi",
            "Users.2.PasswordStatus": "Unlocked",
            "Users.2.PasswordExpiration": "2020-01-01",
            "Security.1.MinimumPasswordScore": 8,
            "LicenseKey": "XXXXX-AAAAA-BBBBB",
            "SNMP.1.AgentCommunity": "site-community",
            "Building": "HDDC",
            "Rack": "HDDC",
            "Room": "DC",
            "Location": "PCI-E Slot 3",
            "PartNumber": "SN37B04254",
            "WWPN": "5000001B44AABBCC",
            "CertCommonName": "ILOTEST0001.example.invalid",
        }
    )
    assert out["Users.2.UserName"] == "DUMMY-User"
    assert out["Users.2.LoginID"] == "DUMMY-User"
    assert out["Users.2.Password"] == "None"
    assert out["Users.2.SHA256Password"] == "DUMMY-Secret"
    assert out["Users.2.SHA256PasswordSalt"] == "DUMMY-Secret"
    assert out["Users.2.IPMIKey"] == "DUMMY-Secret"
    assert out["Users.2.PasswordStatus"] == "Unlocked"
    assert out["Users.2.PasswordExpiration"] == "2020-01-01"
    assert out["Security.1.MinimumPasswordScore"] == 8
    assert out["LicenseKey"] == "DUMMY-LicenseKey"
    assert out["SNMP.1.AgentCommunity"] == "DUMMY-Community"
    assert out["Building"] == "DUMMY-Building"
    assert out["Rack"] == "DUMMY-Rack"
    assert out["Room"] == "DUMMY-Room"
    assert out["Location"] == "PCI-E Slot 3"
    assert out["PartNumber"] == "DUMMY-PartNumber"
    assert out["WWPN"] == "00:1B:44:AA:BB:CC:00:00"
    assert out["CertCommonName"] == cloner.DUMMY_COMMON_NAME


def test_catalog_part_numbers_preserved(cloner):
    out = cloner.sanitize_data(
        {
            "Nic": {"PartNumber": "HMAA8GR7CJR4N-XN"},
            "Psu": {"PartNumber": "PWS-804P-1R"},
            "Dell": {"PartNumber": "0F3F6P"},
        }
    )
    assert out["Nic"]["PartNumber"] == "HMAA8GR7CJR4N-XN"
    assert out["Psu"]["PartNumber"] == "PWS-804P-1R"
    assert out["Dell"]["PartNumber"] == "0F3F6P"


def test_spaced_vendor_common_name_preserved(cloner):
    cn = "Microsoft Corporation UEFI CA 2011"
    out = cloner.sanitize_data({"CommonName": cn})
    assert out["CommonName"] == cn


def test_resource_tokens_in_strings(cloner):
    out = cloner.sanitize_data(
        {
            "Message": "host XCC-7DHE-JZ009GEY reported in",
            "Subject": "CN = ILOSGH029VFCD, O = Hewlett Packard Enterprise",
            "@odata.id": "/redfish/v1/Systems/BQC212600009",
        }
    )
    assert out["Message"] == "host DUMMY-HostName reported in"
    assert out["Subject"] == "CN = DUMMY-HostName, O = Hewlett Packard Enterprise"
    assert out["@odata.id"] == "/redfish/v1/Systems/DUMMY-SystemId"


def test_dirgroup_map_is_unique_and_stable():
    tokens = [
        "dirgroupb3d8954f6ebbe735764e9f7c",
        "dirgroup9d4546a03a03bb977c03086a",
    ]
    id_map = build_dirgroup_id_map(tokens)
    assert id_map["dirgroup9d4546a03a03bb977c03086a"] == "dirgroupDUMMY-1"
    assert id_map["dirgroupb3d8954f6ebbe735764e9f7c"] == "dirgroupDUMMY-2"
    body = {
        "Members": [
            {
                "@odata.id": "/redfish/v1/AccountService/Roles/dirgroup9d4546a03a03bb977c03086a"
            },
            {
                "@odata.id": "/redfish/v1/AccountService/Roles/dirgroupb3d8954f6ebbe735764e9f7c"
            },
        ]
    }
    out = sanitize_redfish(body, id_map=id_map)
    ids = [m["@odata.id"] for m in out["Members"]]
    assert ids[0].endswith("/dirgroupDUMMY-1")
    assert ids[1].endswith("/dirgroupDUMMY-2")
    assert len(set(id_map.values())) == 2


def test_resource_tokens_do_not_mask_firmware_versions():
    uri = "/redfish/v1/UpdateService/FirmwareInventory/Installed-104480-14.28.45.12"
    assert sanitize_resource_tokens(uri) == uri


def test_compressed_ipv6_replaced_whole(cloner):
    out = cloner.sanitize_data(
        {
            "Live": "client a45b:efa6::abcd:1 connected",
            "Broken": "was a45b:efa6::::1",
        }
    )
    assert out["Live"] == "client ::1 connected"
    assert out["Broken"] == "was ::1"


def test_eight_octet_colon_hex_has_no_tail(cloner):
    out = cloner.sanitize_data({"Message": "wwn 50:00:00:1B:44:AA:DD:EE end"})
    assert out["Message"] == f"wwn {cloner.DUMMY_MAC} end"
    assert "DD:EE" not in out["Message"]


def test_admin_message_arg_preserved(cloner):
    out = cloner.sanitize_data({"MessageArgs": ["admin"]})
    assert out["MessageArgs"] == ["admin"]


def test_cert_common_name_canonicalizes_older_placeholders(cloner):
    out = cloner.sanitize_data(
        {
            "Oem": {
                "Hpe": {
                    "Sessions": {
                        "CertCommonName": "DUMMY-HostName",
                        "Other": "unchanged",
                    }
                }
            },
            "CertCommonName": "XCC-7Z73-J30AB503",
        }
    )
    assert out["Oem"]["Hpe"]["Sessions"]["CertCommonName"] == cloner.DUMMY_COMMON_NAME
    assert out["Oem"]["Hpe"]["Sessions"]["Other"] == "unchanged"
    assert out["CertCommonName"] == cloner.DUMMY_COMMON_NAME


def test_snmp_location_and_raw_port_mac(cloner):
    out = cloner.sanitize_data(
        {
            "SNMPv3Agent": {"Location": "HDDC", "Port": 161},
            "Placement": {"Location": "PCI-E Slot 3"},
            "Oem": {"Lenovo": {"PhysicalPortMacAddress": "AABBCCDDEEFF0011"}},
            "CommunityNames": ["site-community", None],
            "ReadCommunities": ["site-community"],
            "TrapCommunities": [""],
        }
    )
    assert out["SNMPv3Agent"]["Location"] == "DUMMY-Location"
    assert out["SNMPv3Agent"]["Port"] == 161
    assert out["Placement"]["Location"] == "PCI-E Slot 3"
    assert out["Oem"]["Lenovo"]["PhysicalPortMacAddress"] == cloner.DUMMY_MAC
    assert out["CommunityNames"] == ["DUMMY-Community", None]
    assert out["ReadCommunities"] == ["DUMMY-Community"]
    assert out["TrapCommunities"] == [""]


def test_openssh_and_firmware_odata_still_preserved(cloner):
    cipher = cloner.sanitize_data({"Cipher": "chacha20-poly1305@openssh.com"})
    assert cipher["Cipher"] == "chacha20-poly1305@openssh.com"
    uri = "/redfish/v1/UpdateService/FirmwareInventory/Installed-104480-14.28.45.12"
    out = cloner.sanitize_data({"@odata.id": uri})
    assert out["@odata.id"] == uri


UNDASHED_DUMMY = "550e8400e29b41d4a716446655440000"


def test_undashed_uuid_and_guid_keys_are_masked(cloner):
    out = cloner.sanitize_data(
        {
            "UUID": "544F9A1C0B2D4E3F8A9B0C1D2E3FE982",
            "GPUGUID": "bc80a1b2c3d4e5f60718293a4b5cE9FA",
        }
    )
    assert out["UUID"] == UNDASHED_DUMMY
    assert out["GPUGUID"] == UNDASHED_DUMMY
    # Idempotent: a second pass leaves the placeholder unchanged.
    assert cloner.sanitize_data(out) == out


def test_undashed_audience_uuid_is_masked(cloner):
    out = cloner.sanitize_data({"Audience": "544F9A1C0B2D4E3F8A9B0C1D2E3FE982"})
    assert out["Audience"] == UNDASHED_DUMMY
    # Lenovo AccountService keeps the audience as a list.
    out = cloner.sanitize_data(
        {"OAuth2": {"Audience": ["544F9A1C0B2D4E3F8A9B0C1D2E3FE982"]}}
    )
    assert out["OAuth2"]["Audience"] == [UNDASHED_DUMMY]


def test_undashed_hex_under_unrelated_key_is_kept(cloner):
    digest = "544F9A1C0B2D4E3F8A9B0C1D2E3FE982"
    out = cloner.sanitize_data({"Checksum": digest})
    assert out["Checksum"] == digest


def test_non_hex_guid_keys_are_kept(cloner):
    out = cloner.sanitize_data(
        {"PermanentPortGUID": "::0", "ProcessorUuidControl": "Loxkxisxxlx"}
    )
    # "::0" is an IPv6 token, so the existing IPv6 rule applies; it must not become a GUID.
    assert out["PermanentPortGUID"] == "::1"
    assert out["ProcessorUuidControl"] == "Loxkxisxxlx"


def test_bare_12_hex_mac_in_address_list_is_masked(cloner):
    out = cloner.sanitize_data(
        {"AssociatedNetworkAddresses": ["BC97E1A2B3C4", "unknown"]}
    )
    assert out["AssociatedNetworkAddresses"] == ["00:1B:44:AA:00:01", "unknown"]


def test_version_strings_not_masked_as_ipv4(cloner):
    out = cloner.sanitize_data(
        {
            "Version": "22.31.1.2",
            "VersionString": "22.31.1.2",
            "Oem": {"Broadcom57508_PhysicalPort1LogicalPort1_EFI": "22.31.1.2"},
            "Message": "see 10.0.0.1",
        }
    )
    assert out["Version"] == "22.31.1.2"
    assert out["VersionString"] == "22.31.1.2"
    assert out["Oem"]["Broadcom57508_PhysicalPort1LogicalPort1_EFI"] == "22.31.1.2"
    assert out["Message"] == "see 192.0.2.1"


def test_bare_12_hex_mac_string_field_is_masked(cloner):
    out = cloner.sanitize_data({"MACAddress": "E43D1AA2B3C4"})
    assert out["MACAddress"] == "00:1B:44:AA:00:01"
