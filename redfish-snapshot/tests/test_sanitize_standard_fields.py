# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Standard Redfish properties that identify a site, a person or a secret.

No capture in the fixtures has values in most of these, so each test plants a canary
value in the place a new vendor or firmware would put it and checks it is gone.
"""

import json

from redfish_snapshot.postprocess import sanitize_mockups
from redfish_snapshot.sanitize import sanitize_path, sanitize_redfish


def _clean(doc):
    return sanitize_redfish(doc)


def _gone(out, *canaries):
    text = json.dumps(out)
    for canary in canaries:
        assert canary not in text, canary


def test_postal_address_placement_and_coordinates():
    doc = {
        "Location": {
            "PostalAddress": {
                "Country": "US",
                "City": "Canaryville",
                "Street": "Canary Road",
                "PostalCode": "80302",
                "Name": "Canary DC",
            },
            "Placement": {"Row": "ROWQ7", "Rack": "RACK99", "RackOffset": 12},
            "Latitude": 40.01,
            "Longitude": -105.27,
            "Info": "Slot 3",
        }
    }
    out = _clean(doc)["Location"]
    _gone(out, "Canary", "80302", "ROWQ7", "RACK99")
    assert out["PostalAddress"]["Country"] == "US"
    assert out["Latitude"] is None and out["Longitude"] is None
    # Location.Info names a slot or bay, not a place.
    assert out["Info"] == "Slot 3"


def test_contact_phone_numbers():
    out = _clean(
        {"Contacts": [{"PhoneNumber": "+1-303-555-0142"}], "AdminPhone": "x4242"}
    )
    _gone(out, "555-0142", "x4242")


def test_secrets_named_by_suffix():
    doc = {
        "SNMP": {"AuthenticationKey": "canary-auth", "EncryptionKey": "canary-priv"},
        "Authentication": {"KerberosKeytab": "BQIAAABHAAIAC0FDTUVDT1JQ"},
        "BindPassword": "canary-bind",
        "PrivacyPassphrase": "canary-pp",
        "AuthToken": "canary-token",
    }
    _gone(_clean(doc), "canary", "BQIAAABH")


def test_settings_named_like_secrets_keep_their_value():
    doc = {
        "Users.1.EnableSNMPv3Passphrase": "Disabled",
        "StrongPassword": "Enabled",
        "EncryptionKey": "0000000000000000",
    }
    assert _clean(doc) == doc


def test_asset_tag_and_serial_key_variants():
    doc = {
        "ServerInfo.1.ServerAssetTag": "CANARYTAG1",
        "ChassisAssetTag": "CANARYTAG2",
        "SerialNum": "CANARY0001",
        "BoardSN": "CANARY0002",
        "AssetTagProtection": "Enabled",
    }
    out = _clean(doc)
    _gone(out, "CANARY")
    assert out["AssetTagProtection"] == "Enabled"


def test_ldap_distinguished_names():
    doc = {
        "Authentication": {"Username": "CN=svc-bmc,OU=Service,DC=canarycorp,DC=local"},
        "BaseDistinguishedNames": ["DC=canarycorp,DC=local"],
        "RemoteRoleMapping": [{"RemoteGroup": "CN=BMC Admins,OU=Groups,DC=canarycorp"}],
    }
    _gone(_clean(doc), "canarycorp", "svc-bmc", "BMC Admins")


def test_upper_and_mixed_case_domain_names():
    doc = {"Realm": "CANARYCORP.LOCAL", "Domain": "Corp.CanaryCorp.com"}
    _gone(_clean(doc), "CANARYCORP", "CanaryCorp")


def test_redfish_type_names_are_not_domains():
    doc = {"@odata.type": "#Manager.v1_5_0.Manager", "MessageId": "Base.1.8.Success"}
    assert _clean(doc) == doc


def test_uri_host_credentials_and_path():
    doc = {
        "Image": "nfs://filer01/isos/jsmith/rhel.iso",
        "Destination": "https://splunkhec:8088/services/collector",
        "TransferUri": "ftp://canary:pw@203.0.113.9/x",
        "PublicationUri": "http://redfish.dmtf.org/schemas/v1/Manager.json",
    }
    out = _clean(doc)
    _gone(out, "filer01", "jsmith", "splunkhec", "canary:pw", "203.0.113.9")
    assert out["Image"] == "nfs://DUMMY.example.invalid/DUMMY-Path"
    assert out["PublicationUri"] == doc["PublicationUri"]


def test_single_label_ntp_and_dns_servers():
    out = _clean({"NTPServers": ["ntp1", "localhost", "10.1.2.3", ""]})
    assert out["NTPServers"] == ["DUMMY.example.invalid", "localhost", "192.0.2.1", ""]


def test_iscsi_and_nvme_qualified_names():
    doc = {
        "InitiatorName": "iqn.1994-05.com.redhat:canaryhost",
        "Nqn": "nqn.2014-08.com.canarycorp:nvme:prod42",
    }
    out = _clean(doc)
    _gone(out, "canary", "prod42")
    assert out["InitiatorName"] == "iqn.2000-01.invalid.example:DUMMY"


def test_customer_strings_and_keys():
    doc = {
        "Context": "canary-splunk",
        "SysContact": "Canary NOC",
        "KeyString": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICanaryCanary jsmith@laptop",
        "Message": "key ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCanary jsmith@laptop added",
        "EndorsementKey": "canaryEK",
    }
    _gone(_clean(doc), "anary", "jsmith")


def test_site_certificate_subject_is_replaced_and_vendor_ca_kept():
    site = {
        "Subject": {
            "Organization": "Canary Corp",
            "City": "Canaryville",
            "Country": "US",
        }
    }
    vendor = {"Issuer": {"Organization": "Microsoft Corporation", "City": "Redmond"}}
    out = _clean(site)
    _gone(out, "Canary")
    assert out["Subject"]["Country"] == "US"
    assert _clean(vendor) == vendor
    dell = {"SecurityCertificate.1.SubjectOrganization": "Canary Corp"}
    _gone(_clean(dell), "Canary")


def test_truncated_and_headerless_certificates():
    b64 = "MIIDdzCCAl+gAwIBAgIEAgAAuTANBgkqhkiG9w0BAQUFADBaMQswCQYDVQQGEwJJRTESMBAG"
    doc = {
        "CertificateString": b64,
        "Other": "-----BEGIN CERTIFICATE-----\r\n" + b64 + "\r\n",
    }
    _gone(_clean(doc), "MIIDdzCC")


def test_certificate_fingerprint():
    out = _clean({"Fingerprint": "ABCDEF0123456789ABCDEF0123456789ABCDEF01"})
    assert out["Fingerprint"] == "DUMMY-Fingerprint"


def test_distinct_uuids_get_distinct_placeholders():
    a = "1e7b2c4f-0a33-4a5e-9b1e-2f6d8c9a1b77"
    b = "2e7b2c4f-0a33-4a5e-9b1e-2f6d8c9a1b77"
    id_map: dict = {}
    out = sanitize_redfish(
        {"Members": [{"Id": a}, {"Id": b}, {"Ref": a}]}, id_map=id_map
    )
    ids = [m.get("Id") or m.get("Ref") for m in out["Members"]]
    assert ids[0] != ids[1] and ids[0] == ids[2]
    # Placeholders are left alone on a second run.
    assert sanitize_redfish(out, id_map={}) == out


def test_path_is_sanitized_like_its_odata_id():
    uuid = "1e7b2c4f-0a33-4a5e-9b1e-2f6d8c9a1b77"
    id_map: dict = {}
    body = sanitize_redfish({"@odata.id": f"/redfish/v1/Systems/{uuid}"}, id_map=id_map)
    rel = sanitize_path(f"redfish/v1/Systems/{uuid}/index.json", id_map=id_map)
    assert rel == body["@odata.id"].lstrip("/") + "/index.json"
    assert uuid not in rel


def test_firmware_version_in_path_is_not_an_address():
    path = "/redfish/v1/UpdateService/FirmwareInventory/Current-110287-8.11.2.0.18-26__RAID.SL.3-1"
    assert sanitize_path(path) == path
    assert sanitize_path(path + "/Oem/Dell/X") == path + "/Oem/Dell/X"


def test_uuid_resource_id_is_removed_from_directory_names(tmp_path):
    uuid = "1e7b2c4f-0a33-4a5e-9b1e-2f6d8c9a1b77"
    root = tmp_path / "Vendor" / "Model" / "original"
    doc_dir = root / "redfish" / "v1" / "Systems" / uuid
    doc_dir.mkdir(parents=True)
    (doc_dir / "index.json").write_text(
        json.dumps({"@odata.id": f"/redfish/v1/Systems/{uuid}", "Id": uuid})
    )
    (root.parent / "metadata.json").write_text(
        json.dumps({"collected_urls": [f"/redfish/v1/Systems/{uuid}"]})
    )
    sanitize_mockups([root], [root.parent / "metadata.json"], log=lambda *_: None)
    files = [p.relative_to(root).as_posix() for p in root.rglob("index.json")]
    assert len(files) == 1 and uuid not in files[0]
    body = json.loads((root / files[0]).read_text())
    assert files[0] == body["@odata.id"].lstrip("/") + "/index.json"
    assert uuid not in (root.parent / "metadata.json").read_text()
