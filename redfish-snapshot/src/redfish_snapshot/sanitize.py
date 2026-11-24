# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Redfish payload sanitizer shared by snapshots and fixtures rewrites."""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, Iterable, Mapping, Optional


# Built-in metric report names in the Dell, iLO, and XCC fixture catalogs.
_STANDARD_REPORTS = frozenset(
    """
AggregationMetrics CPUMemMetrics CPURegisters CPUSensor FCPortStatistics FCSensor
FPGASensor FanSensor GPUMetrics GPUStatistics MemoryMetrics MemorySensor NICSensor
NICStatistics NVMeSMARTData PSUMetrics PowerMetrics PowerStatistics SFPTransceiver
Sensor SerialLog StorageDiskSMARTData StorageSensor SystemUsage ThermalMetrics ThermalSensor
""".split()
)
_STANDARD_REPORTS |= {
    name + suffix
    for name in (
        "AvgCPU0Freq",
        "AvgCPU1Freq",
        "CPU0Power",
        "CPU1Power",
        "CPUICUtil",
        "CPUUtil",
        "IOBusUtil",
        "JitterCount",
        "MemoryBusUtil",
    )
    for suffix in ("", "Custom1", "Custom2", "Custom3", "Custom4")
}
_STANDARD_REPORTS |= {
    name + suffix
    for name in (
        "CPUPowerMetrics",
        "CPUTemp",
        "CPUUtilizationStats",
        "InletAirTemp",
        "MemoryUtilizationStats",
        "PowerMetrics",
        "PowerSupplyStats",
    )
    for suffix in ("", "Event")
}
_REPORT_PATH = re.compile(
    r"(/TelemetryService/MetricReport(?:Definitions|s)/)([^/#?\s\"<>]+)"
)
_CERT_DATES = {
    "ValidFrom": 2000,
    "ValidTo": 2030,
    "ValidNotBefore": 2000,
    "ValidNotAfter": 2030,
    "CertValidFrom": 2000,
    "CertValidTo": 2030,
}


def _report_path(match, id_map):
    token = match[2]
    if token in _STANDARD_REPORTS or re.fullmatch(r"DUMMY-Report-\d+", token):
        return match[0]
    alias = RedfishSanitizer._stable_placeholder(
        id_map, "telemetry", token, lambda n: f"DUMMY-Report-{n}"
    )
    return match[1] + alias


def standard_boot_certificate_uri(doc: dict) -> str | None:
    """Canonical URI shared by a Dell standard Secure Boot certificate and its OEM record."""
    uri = doc.get("@odata.id")
    if not isinstance(uri, str) or not isinstance(doc.get("Id"), str):
        return None
    parts = uri.split("/")
    if parts[-1] != doc["Id"] or not re.fullmatch(r"StdSecbootpolicy\.\d+", parts[-1]):
        return None
    if "/SecureBoot/SecureBootDatabases/" in uri and parts[-2] == "Certificates":
        # Dell uses "DB" in its OEM path and "db" in the standard resource URI.
        parts[-3] = parts[-3].lower()
        return "/".join(parts)
    if (
        "/SecureBoot/Oem/Dell/Certificates/" in uri
        and doc.get("SecureBootPolicy") == "Standard"
    ):
        prefix, name = uri.split("/SecureBoot/Oem/Dell/Certificates/", 1)
        database, sep, cert_id = name.partition("/")
        if sep and cert_id == doc["Id"]:
            return f"{prefix}/SecureBoot/SecureBootDatabases/{database.lower()}/Certificates/{cert_id}"
    return None


def certificate_document(doc):
    return "Certificate" in str(doc.get("@odata.type", "")).split(".", 1)[0]


def _mask_certificate_fields(doc):
    certificate = certificate_document(doc)
    public = standard_boot_certificate_uri(doc) is not None
    for key in list(doc):
        leaf = key.rsplit(".", 1)[-1]
        attribute = re.fullmatch(r"SecurityCertificate\.\d+\.(.+)", key)
        if not (certificate or attribute):
            continue
        if not public and leaf in _CERT_DATES and doc[key]:
            doc[key] = f"{_CERT_DATES[leaf]}-01-01T00:00:00Z"
        if not public and leaf in {
            "IssuerCountryCode",
            "SubjectCountryCode",
            "IssuerCountryCode_CC",
            "SubjectCountryCode_CC",
        }:
            doc.pop(key)
    if certificate and not public:
        for party in ("Issuer", "Subject"):
            if isinstance(doc.get(party), dict):
                doc[party].pop("Country", None)


class RedfishSanitizer:
    """Replace secrets and customer identifiers in Redfish JSON."""

    # RFC 5737 test net; use for all sanitized IPv4
    DUMMY_IPV4 = "192.0.2.1"
    DUMMY_IPV6 = "::1"
    DUMMY_UUID = "550e8400-e29b-41d4-a716-446655440000"
    DUMMY_MAC = "00:1B:44:AA:BB:CC"
    DUMMY_EMAIL = "DUMMY@example.invalid"
    # Stand-in for any tenant- or customer-owned DNS name (allowlist-only; no blocklists).
    DUMMY_FQDN = "DUMMY.example.invalid"
    DUMMY_PEM_BLOCK = (
        "-----BEGIN CERTIFICATE-----\nDUMMY-PEM-REDACTED\n-----END CERTIFICATE-----\n"
    )
    DUMMY_COMMON_NAME = "DUMMY-CommonName"
    DUMMY_WWN = "00:1B:44:AA:BB:CC:00:00"
    DUMMY_SECRET = "DUMMY-Secret"
    DUMMY_COMMUNITY = "DUMMY-Community"
    DUMMY_USER = "DUMMY-User"
    DUMMY_HOSTNAME = "DUMMY-HostName"
    DUMMY_SYSTEM_ID = "DUMMY-SystemId"

    _SECRET_LEAVES = frozenset(
        {
            "Password",
            "IPMIKey",
            "MD5v3Key",
            "SHA1v3Key",
            "SHA256Password",
            "SHA256PasswordSalt",
            "SHA384v3Key",
            "SHA512v3Key",
        }
    )
    _COMMUNITY_LEAVES = frozenset(
        {
            "Community",
            "CommunityString",
            "TrapCommunity",
            "AgentCommunity",
            "CommunityName",
        }
    )
    # Secrets named by suffix: BindPassword, PrivacyPassphrase, CHAPSecret, KerberosKeytab,
    # AuthToken, and the SNMPv3 AuthenticationKey and EncryptionKey of ManagerAccount.
    _SECRET_SUFFIXES = (
        "Password",
        "Passphrase",
        "PassPhrase",
        "Secret",
        "Keytab",
        "Token",
        "AuthenticationKey",
        "EncryptionKey",
        "PrivateKey",
        "PreSharedKey",
    )
    _SITE_LEAVES = frozenset({"Building", "Rack", "Room", "DataCenter"})
    # Location.Placement values other than Rack that name a place in the site.
    _PLACEMENT_LEAVES = frozenset({"Row", "AdditionalInfo"})
    # Location.Latitude, Longitude and AltitudeMeters are numbers; they become null.
    _COORDINATE_LEAVES = frozenset({"Latitude", "Longitude", "AltitudeMeters"})
    # Lists of host names: a single-label name (ntp1) has no shape a pattern can find.
    _HOST_LIST_KEYS = frozenset(
        {"NTPServers", "NameServers", "StaticNameServers", "SearchDomains"}
    )
    # Certificate subject and issuer fields other than the common name.
    _CERT_NAME_FIELDS = frozenset(
        {"Organization", "OrganizationalUnit", "City", "State"}
    )
    _CERT_NAME_LEAF_RE = re.compile(
        r"^(?:Subject|Issuer|Csr)(?:Organization|OrganizationalUnit|OrganizationUnit"
        r"|OrganizationName|City|Locality|State)(?:_\w+)?$"
    )
    # Subject and issuer values of public vendor and CA certificates (Secure Boot, TPM, BMC
    # defaults). Any other value is the site's own CA or certificate and is replaced.
    _PUBLIC_CERT_NAMES = frozenset(
        {
            "Americas",
            "Antares",
            "Canonical Ltd.",
            "Cisco",
            "CODE-SIGN",
            "Compute Devices",
            "Dell Inc",
            "Dell Inc.",
            "Dell EMC",
            "Dell Technologies Inc.",
            "Douglas",
            "Hewlett Packard Enterprise",
            "Hewlett Packard Enterprise Company",
            "Hewlett Packard Enterprise Development",
            "Hewlett-Packard Company",
            "Houston",
            "HPE",
            "IDRAC",
            "Inventec",
            "Isle of Man",
            "Lenovo",
            "Long Lived CodeSigning Certificate",
            "Microsoft Corporation",
            "NC",
            "Nuvoton Technology Corporation",
            "OpenBMC",
            "Palo Alto",
            "PowerEdge",
            "PROD",
            "Redmond",
            "Remote Access Group",
            "Round Rock",
            "RTP",
            "Secure Boot",
            "Server and Infrastructure Systems",
            "Shanghai",
            "Supermicro",
            "Texas",
            "Toliman",
            "TX",
            "VMware, Inc.",
            "Washington",
            "California",
            "XU",
        }
    )
    # sysLocation on the SNMP agent. Other Location values are slot and bay names.
    _SNMP_LOCATION_PARENTS = frozenset({"SNMPv3Agent"})
    _RAW_MAC_LEAVES = frozenset({"PhysicalPortMacAddress"})
    _RAW_MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$|^[0-9A-Fa-f]{16}$")
    _WWN_LEAVES = frozenset({"WWN", "WWNN", "WWPN"})
    # Storage device identifiers (drive NAA names, virtual disk unique ids). Each is replaced
    # by its own value in the same format, so distinct devices stay distinct.
    _STORAGE_ID_LEAVES = frozenset({"DurableName", "VolumeUniqueIdentifier", "EUI64"})
    # What _storage_id_placeholder writes: optional prefix, then zeros and a short counter.
    _STORAGE_ID_PLACEHOLDER_RE = re.compile(r"(?:[A-Za-z]{2,4}:)?0{4,}[0-9A-F]{1,4}")
    _ACCOUNT_LEAVES = frozenset(
        {"UserName", "LoginID", "LoginName", "Account", "AccountName"}
    )
    # Per-device identifiers that have a dedicated leaf: Dell NodeID and UniqueID, licence IDs,
    # CPU PPIN, iLO ChipId, SAS address, config hashes, and LogicalDriveName (holds a controller serial).
    _DEVICE_ID_LEAVES = frozenset(
        {
            "NodeID",
            "UniqueID",
            "ExpressServiceCode",
            "EntitlementID",
            "EntitlementId",
            "ProtectedIdentificationNumber",
            "ChipId",
            "SASAddress",
            "PPID",
            "SystemConfigHash",
            "LogicalDriveName",
        }
    )
    # Opaque or customer-set values replaced whole: SNMP engine IDs, SSH host keys, signatures,
    # DUIDs, iSCSI and NQN names, backup file names, Lenovo ArchitectureId, and contact names.
    _OPAQUE_LEAVES = frozenset(
        {
            "EngineID",
            "SNMPv3EngineID",
            "ArchitectureId",
            "DUID",
            "SSHHostKey",
            "Signature",
            "iSCSIInitiatorName",
            "IscsiInitiatorName",
            "NvmeofHostDellNqn",
            "BackupFileLocation",
            "extref",
            "RecipientName",
            "ContactName",
            "ContactPerson",
            "LicenseSeats",
            # Customer-set strings: event subscription context, SNMP system group, SSH user
            # keys, and the TPM endorsement key.
            "Context",
            "SysContact",
            "SysName",
            "SysLocation",
            "KeyString",
            "SSHPublicKey",
            "PublicKey",
            "EndorsementKey",
            "GPSCoords",
            # TPM and SPDM measurements of this host (ComponentIntegrity).
            "Measurement",
        }
    )
    _HOST_LEAVES = frozenset({"HostName", "FQDN", "DNSRacName", "DNSDomainName"})
    _PHONE_SUFFIXES = ("Phone", "PhoneNumber")
    # NVIDIA/Mellanox adapter serials are stored as PartNumber (SN37B04254).
    # Catalog parts keep hyphens or a different prefix (HMAA8GR7CJR4N-XN).
    _SN_PARTNUMBER_RE = re.compile(r"^SN[0-9A-Z]{5,}$")
    _XCC_RE = re.compile(r"\bXCC-[A-Za-z0-9-]+\b")
    _ILO_RE = re.compile(r"\bILO[A-Z0-9]{6,}(?:\.[A-Za-z0-9.-]+)?")
    _BQC_RE = re.compile(r"\bBQC[0-9A-Z]{6,}\b")
    DIRGROUP_RE = re.compile(r"dirgroup[0-9a-fA-F]{8,}")
    # 8 or more colon-separated octets (WWNs). Applied before the 6-octet MAC regex
    # so the tail of a longer address is not left behind.
    _COLON_HEX_LONG_RE = re.compile(
        r"\b(?:[0-9A-Fa-f]{1,2}:){7,}[0-9A-Fa-f]{1,2}\b",
        re.IGNORECASE,
    )
    # Whole IPv6 token, including compressed and malformed forms that contain "::".
    _COMPRESSED_IPV6_RE = re.compile(
        r"(?<![0-9A-Za-z])(?:"
        r"(?:[0-9A-Fa-f]{1,4}:){1,7}:[0-9A-Fa-f:]*|"
        r":(?::[0-9A-Fa-f:]*)"
        r")(?![0-9A-Za-z])"
    )

    # Do not treat SSH algorithm @domain strings as emails.
    _EMAIL_SKIP_DOMAINS = frozenset({"openssh.com", "libssh.org"})
    _PEM_BLOCK_RE = re.compile(
        r"-----BEGIN ([A-Z0-9 -]+)-----\s*.*?-----END \1-----\s*",
        re.DOTALL | re.IGNORECASE,
    )
    # A PEM block cut off before its END line (iLO truncates CertificateString at 2047).
    _PEM_OPEN_RE = re.compile(r"-----BEGIN [A-Z0-9 -]+-----[\sA-Za-z0-9+/=]*$")
    _BARE_BASE64_RE = re.compile(r"[A-Za-z0-9+/=\s]{64,}")
    # LDAP distinguished names (bind DNs, base DNs, remote groups): two or more RDNs.
    _DN_RE = re.compile(
        r"\b(?:CN|OU|DC|O|L|ST|UID)=[^,=\"]+(?:,\s*(?:CN|OU|DC|O|L|ST|C|UID|E)=[^,=\"]*)+",
        re.IGNORECASE,
    )
    DUMMY_DN = "CN=DUMMY,DC=example,DC=invalid"
    # scheme://[user[:password]@]host[:port][/path]. Matched before the FQDN pass, so a
    # single-label host (nfs://filer01/...) and the path under it are replaced too.
    _URI_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]{1,15})://([^\s\"'<>]*)")
    # iSCSI and NVMe qualified names: iqn.1994-05.com.redhat:<host>, nqn.2014-08.com.x:<host>.
    _QUALIFIED_NAME_RE = re.compile(
        r"\b(iqn|nqn)\.\d{4}-\d{2}\.[A-Za-z0-9.-]+(?::[^\s\",;]*)?", re.IGNORECASE
    )
    # OpenSSH public keys, with the trailing user@host comment.
    _SSH_PUBLIC_KEY_RE = re.compile(
        r"\b(?:ssh-(?:rsa|ed25519|dss)|ecdsa-sha2-nistp\d+|sk-[a-z0-9-]+@openssh\.com)"
        r"\s+AAAA[0-9A-Za-z+/]+=*(?:\s+[^\s\",]+)?"
    )
    # Upper- or mixed-case names are kept (Redfish types such as Manager.Manager) unless the
    # last label is one of these DNS suffixes (CORP.EXAMPLE.COM, Mail.Example.com).
    _DNS_SUFFIX_LABELS = frozenset(
        {
            "com",
            "net",
            "org",
            "edu",
            "gov",
            "mil",
            "biz",
            "info",
            "io",
            "arpa",
            "local",
            "localdomain",
            "lan",
            "corp",
            "internal",
            "intranet",
            "home",
        }
    )
    _EMAIL_RE = re.compile(
        r"\b[A-Za-z0-9](?:[A-Za-z0-9._%+-]*[A-Za-z0-9])?@"
        r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,}\b"
    )
    _MAILTO_RE = re.compile(r"\bmailto:([^>\s\"']+)", re.I)
    # Multi-label hostnames; final label must be alphabetic (avoids 1.2.3.4-style matches).
    _FQDN_RE = re.compile(
        r"(?<![A-Za-z0-9@])"
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z]{2,63}"
        # A following '-' means the label continues (e.g. #redfish-schema-v1.redfish-schema-v1).
        r"(?![A-Za-z0-9.-])",
        re.IGNORECASE,
    )
    # Rightmost label is a common path/file suffix, not a DNS TLD.
    _FQDN_SKIP_TLD = frozenset(
        {
            "json",
            "xml",
            "html",
            "htm",
            "yaml",
            "yml",
            "css",
            "js",
            "mjs",
            "cjs",
            "ts",
            "md",
            "txt",
            "csv",
            "svg",
            "png",
            "jpg",
            "jpeg",
            "gif",
            "webp",
            "wasm",
            "pdf",
            "xsl",
            "xslt",
            "map",
            "efi",
            "iso",
            "img",
            "bin",
            "cap",
        }
    )
    # Reserved / schema / toolchain hosts — not tenant-owned (suffix match, longest wins in loop).
    _FQDN_SAFE_SUFFIXES = (
        "dmtf.org",
        "iana.org",
        "ietf.org",
        "example.com",
        "example.org",
        "example.net",
        "example.invalid",
        "openssh.com",
        "libssh.org",
        "localhost",
        # Reversed form used by the IQN and NQN placeholders (iqn.2000-01.invalid.example).
        "invalid.example",
    )
    _UUID_RE = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    )
    _MAC_RE = re.compile(r"\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
    # Whole-value bare MAC (no separators), e.g. AssociatedNetworkAddresses on Lenovo ports.
    _BARE_MAC12_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
    # Whole-value undashed GUID (32 hex), e.g. Lenovo NetworkAdapter UUID, GPUGUID.
    _UNDASHED_GUID_RE = re.compile(r"^[0-9A-Fa-f]{32}$")
    # Identifier forms the key rules cannot see, matched inside free text and paths.
    _MAC_IN_PATH_RE = re.compile(r"(MAC\()([0-9A-Fa-f]{12})(?=,)")  # UEFI device path
    _ILO_MAC_NAME_RE = re.compile(r"\b(ilo-)([0-9A-Fa-f]{12})\b", re.IGNORECASE)
    _BYTE_RUN_MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[ :-]){5,7}[0-9A-Fa-f]{2}\b")
    _SN_PAREN_RE = re.compile(r"(\((?:SN|SKU NO): )[^)]*\)")
    _SN_HASH_RE = re.compile(r"(\bSN#\s+)[A-Z0-9]{7,10}\b")
    _HSTNAME_KV_RE = re.compile(r"\bHstName=[^,\s]+")
    # Dell licence entitlement IDs, also used as the licence Id, URL and directory name.
    _DLF_FD_ID_RE = re.compile(r"\b(?:DLF|FD)\d{13,14}\b")
    # Task monitor URLs end in a random token (/redfish/v1/TaskMonitor/<token>).
    _TASK_MONITOR_RE = re.compile(r"(/TaskMonitors?/)(?!DUMMY)[A-Za-z0-9_-]{16,}")
    _OME_ID_RE = re.compile(
        r"\bOME_[0-9a-fA-F]{12}\b"
    )  # OpenManage Enterprise instance
    # Bare hh:mm:ss would otherwise match the IPv6 shape and turn into ::1.
    _IPV6_LIKE_RE = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F]{1,4}\b")
    _CLOCK_TIME_RE = re.compile(r"\d{1,2}:\d{2}:\d{2}")
    # Dell job and request ids: 12 digits that encode a creation time. A placeholder starts
    # with eight zeros, so a second run leaves it alone.
    _JOB_ID_RE = re.compile(
        r"(?<![0-9A-Za-z])(JID|RID)_(?!00000000)(\d{12})(?![0-9A-Za-z])"
    )
    _IKVM_URI_RE = re.compile(r"/redfish/(?!DUMMY)[A-Za-z0-9]{10,}\.IKVM")
    # Drive and controller serials inside boot strings and default logical-drive names.
    _LENOVO_BOOT_SN_RE = re.compile(r"(\)\s+)[A-Z0-9]{10,20}(\s+-)")
    _INTEL_BOOT_SN_RE = re.compile(r"^(UEFI \S+ \S+ )[A-Z0-9]{10,}(\s*)$")
    _HPE_LOGICAL_DRIVE_RE = re.compile(r"\b([0-9A-F]{8})[A-Z0-9]{14}( [0-9A-F]{4})\b")
    # Phrases in log text that name an account. Group 1 is the account.
    USER_PATTERNS = (
        re.compile(r"\blog in for (\S+?) from\b"),
        re.compile(r"\blogged in using (\S+?),"),
        re.compile(r"\bby user (\S+?)(?=[.\s,;)]|$)"),
        re.compile(r"\bUser (\S+?) (?:created|deleted|modified|logged|login)"),
        re.compile(r"\blogin failed: (\S+)"),
        re.compile(r"\bLogin (?:success|failure)[^:]*: (\S+)"),
    )
    USER_ALLOWLIST = frozenset(
        {
            "root",
            "ADMIN",
            "admin",
            "Administrator",
            "USERID",
            "IPMIKCS",
            "IPMIMBOX",
            "LXPM",
            "system",
            "REDFISH",
            "Redfish",
            "IPMI",
            "RACADM",
            "GUI",
            "SSH",
        }
    )
    # GPT partition GUIDs in boot strings use underscores (D9A45241_..._EFI_redhat_shimx64_efi).
    _UNDERSCORE_GUID_RE = re.compile(
        r"(?<![0-9A-Za-z])[0-9a-fA-F]{8}(?:_[0-9a-fA-F]{4}){3}_[0-9a-fA-F]{12}(?![0-9A-Za-z])"
    )
    # Lenovo FoD key and licence IDs (52-3C18A4EBBB0556B4) in paths, Ids and @odata.id.
    _FOD_KEY_ID_RE = re.compile(r"(?<![0-9A-Za-z])\d{1,6}-[0-9A-F]{16}(?![0-9A-Za-z])")
    # LLDP-reported switch port names show the site's switch vendor and port layout.
    _SWITCH_PORT_LEAVES = frozenset(
        {"SwitchPortConnectionID", "SwitchPortConnection", "SwitchConnectionID"}
    )
    _SWITCH_STATUS_VALUES = frozenset(
        {"No Link", "Not Supported", "Not Available", "Unknown"}
    )

    # JSON keys whose string values (or list string elements) must receive MAC substitution.
    MAC_SUBSTITUTION_KEYS = frozenset(
        {
            "AssociatedNetworkAddresses",
            "AssociatedMACAddresses",
            "PermanentMACAddress",
            "MACAddress",
            "CurrentMACAddress",
            "BackupMACAddress",
            "VirtualMACAddress",
        }
    )

    # Subject/Issuer CommonName values that are generic (do not replace).
    _GENERIC_COMMON_NAMES = frozenset(
        {
            "",
            "US",
            "IN",
            "CA",
            "NC",
            "TX",
            "UK",
            "GB",
            "RTP",
            "Houston",
            "America",
            "Lenovo",
            "Dell Inc.",
            "Dell",
            "HPE",
            "Hewlett Packard Enterprise",
            "Supermicro",
            "OpenBMC",
            "testhost",
            "localhost",
        }
    )

    # Keys that may contain serial numbers (exact key match or key ends with these)
    SERIAL_KEY_PATTERNS = (
        "SerialNumber",
        "SerialNo",
        "SKU",
        "AssetTag",
        "ServiceTag",
        "ServiceIdentification",
        "BoardSerialNumber",
        "SystemSerialNo",
        "ChassisSerialNo",
        "BackplaneSerialNo",
        "SystemBoardSerialNumber",
        "FRUSerialNumber",
    )

    # Serial keys by suffix: Serial, SerialNum, and BoardSN-style names (lower case before SN).
    _SERIAL_SUFFIX_RE = re.compile(r"(?:Serial|SerialNum|[a-z]SN)$")

    def _mask_serial_value(self, key: str) -> bool:
        """True if this key should get a serial placeholder."""
        # AssetTag matches as a suffix only: AssetTagProtection is a boolean setting.
        if key.endswith("AssetTag") or self._SERIAL_SUFFIX_RE.search(key):
            return True
        for pat in self.SERIAL_KEY_PATTERNS:
            if key == pat or (pat in key and pat != "AssetTag"):
                return True
        return False

    @staticmethod
    def _stable_placeholder(
        id_map: Dict[str, str],
        namespace: str,
        value: str,
        make: Any,
    ) -> str:
        """The same placeholder for the same value everywhere in one id_map, a new one otherwise.

        Placeholders are numbered in the order values first appear, so distinct devices get
        distinct placeholders and one device keeps its placeholder across documents.
        """
        token = f"{namespace}:{value}"
        existing = id_map.get(token)
        if existing is not None:
            return existing
        count_key = f"#count:{namespace}"
        n = int(id_map.get(count_key, "0")) + 1
        id_map[count_key] = str(n)
        id_map[token] = make(n)
        return id_map[token]

    # Placeholder MACs keep this OUI. The last two octets are the counter, so each
    # distinct address stays distinct and a second run leaves the value alone.
    _MAC_PLACEHOLDER_OUI = "001B44AA"

    @staticmethod
    def _mac_key(value: str) -> str:
        return re.sub(r"[^0-9A-Fa-f]", "", value).upper()

    @classmethod
    def _is_mac_placeholder(cls, value: str) -> bool:
        """True when the whole value is one placeholder MAC, separators allowed."""
        stripped = value.strip()
        key = cls._mac_key(stripped)
        if len(key) != 12 or not key.startswith(cls._MAC_PLACEHOLDER_OUI):
            return False
        return (
            re.fullmatch(r"[0-9A-Fa-f]{2}(?:[:\-\s]?[0-9A-Fa-f]{2}){5}", stripped)
            is not None
        )

    @staticmethod
    def _format_mac(n: int) -> str:
        return f"00:1B:44:AA:{(n >> 8) & 0xFF:02X}:{n & 0xFF:02X}"

    @classmethod
    def _assign_mac(cls, id_map: Dict[str, str], value: str) -> str:
        """One colon-form placeholder per distinct 6-octet MAC. A placeholder is kept."""
        key = cls._mac_key(value)
        if len(key) != 12:
            return cls.DUMMY_MAC
        if key.startswith(cls._MAC_PLACEHOLDER_OUI):
            return cls._format_mac(int(key[8:], 16))
        return cls._stable_placeholder(id_map, "mac", key, cls._format_mac)

    def _mac_repl(self, id_map: Dict[str, str]):
        def repl(m: re.Match) -> str:
            raw = m.group(0)
            if self._is_mac_placeholder(raw):
                return raw
            colon = self._assign_mac(id_map, raw)
            return colon if re.search(r"[:-]", raw) else colon.replace(":", "")

        return repl

    @staticmethod
    def _storage_id_placeholder(value: str, leaf: str, n: int) -> str:
        """A placeholder in the shape of ``value``: same prefix and hex width, new digits.

        ``NAA:60000000000000A5`` becomes ``NAA:0000000000000001``. A value that is not
        prefix plus hex becomes ``DUMMY-<leaf>-<n>``.
        """
        m = re.fullmatch(r"((?:[A-Za-z]{2,4}:)?)([0-9A-Fa-f]{4,})", value)
        if m is not None:
            width = len(m.group(2))
            if n < 16**width:
                return f"{m.group(1)}{n:0{width}X}"
        return f"DUMMY-{leaf}-{n}"

    # IPv4-shaped Dell/HPE firmware strings (e.g. 2.85.85.85) must not be treated as addresses.
    SKIP_IPV4_SUBSTITUTION_KEYS = frozenset(
        {
            "FirmwareVersion",
            "FirmwarePackageVersion",
            "ControllerFirmwareVersion",
            "MediaFirmwareVersion",
            "UefiVersion",
            "BiosVersion",
            "PrmFirmwareVersion",
            "Version",
            "VersionString",
        }
    )
    # Broadcom Oem firmware component keys (e.g. ..._PhysicalPort1LogicalPort1_EFI) hold versions.
    _FIRMWARE_COMPONENT_KEY_SUFFIXES = ("_EFI", "_MBA", "_BootCode", "_FirmwareBundle")
    BIOS_ATTR_SKIP_IPV4_KEYS = frozenset({"SystemMeVersion", "SmuVersion"})
    _FIRMWARE_INVENTORY_ID_TAIL = re.compile(
        r"^(?:Installed|Previous|Current|Downgrade|Nested|Application)-\d+-[\d.]+(?:-\d+)*(?:__[\w.%-]+)?$"
    )

    @staticmethod
    def _odata_container_type(d: dict) -> Optional[str]:
        t = d.get("@odata.type")
        return t if isinstance(t, str) else None

    def _skip_ipv4_substitution(
        self,
        field_name: Optional[str],
        parent_key: Optional[str],
        container_type: Optional[str],
        s: str,
    ) -> bool:
        if field_name in self.SKIP_IPV4_SUBSTITUTION_KEYS:
            return True
        if field_name and field_name.endswith(self._FIRMWARE_COMPONENT_KEY_SUFFIXES):
            return True
        if parent_key == "Attributes" and field_name in self.BIOS_ATTR_SKIP_IPV4_KEYS:
            return True
        if field_name in ("@odata.id", "Id"):
            # Any segment: the Id also leads the paths of its Oem sub-resources.
            if any(self._FIRMWARE_INVENTORY_ID_TAIL.match(seg) for seg in s.split("/")):
                return True
        if (
            field_name == "Version"
            and container_type
            and "SoftwareInventory" in container_type
        ):
            return True
        return False

    def _replace_pem_blocks(self, s: str) -> str:
        """Replace PEM-encoded blocks (certificate, CSR, etc.) with a fixed placeholder."""
        s = self._PEM_BLOCK_RE.sub(self.DUMMY_PEM_BLOCK, s)
        return self._PEM_OPEN_RE.sub(self.DUMMY_PEM_BLOCK, s)

    def _site_certificate_name(self, value: str) -> bool:
        """True for a subject or issuer name that is not a public vendor or CA name.

        A name has three letters in a row; shorter values are parse debris (iLO returns some).
        """
        return value not in self._PUBLIC_CERT_NAMES and bool(
            re.search(r"[A-Za-z]{3}", value)
        )

    def _replace_uris(self, s: str) -> str:
        """Replace the host, credentials and path of a URI whose host is not public."""

        def repl(m: re.Match) -> str:
            scheme, rest = m.group(1), m.group(2)
            cut = min((i for i in (rest.find(c) for c in "/?#") if i >= 0), default=-1)
            authority, tail = (rest, "") if cut < 0 else (rest[:cut], rest[cut:])
            hostport = authority.rsplit("@", 1)[-1]
            host, port = hostport, ""
            if not hostport.startswith("[") and hostport.count(":") == 1:
                host, port = hostport.split(":")
                port = ":" + port
            if "@" not in authority and (
                host == self.DUMMY_IPV4 or self._fqdn_is_allowlisted(host)
            ):
                return m.group(0)
            path = "/DUMMY-Path" if tail.strip("/") else tail
            return f"{scheme}://{self.DUMMY_FQDN}{port}{path}"

        return self._URI_RE.sub(repl, s)

    def _replace_qualified_names(self, s: str) -> str:
        """iSCSI IQNs and NVMe NQNs name the host (iqn.1994-05.com.redhat:db01)."""

        return self._QUALIFIED_NAME_RE.sub(
            lambda m: f"{m.group(1).lower()}.2000-01.invalid.example:DUMMY", s
        )

    def _uuid_repl(self, id_map: Dict[str, str]):
        """One placeholder UUID per distinct UUID, so resources keyed by UUID stay distinct."""
        prefix = self.DUMMY_UUID[:24]

        def repl(m: re.Match) -> str:
            value = m.group(0).lower()
            if value.startswith(prefix):
                return m.group(0)
            return self._stable_placeholder(
                id_map, "uuid", value, lambda n: f"{prefix}{n:012x}"
            )

        return repl

    def _replace_emails_in_string(self, s: str) -> str:
        """Mask email addresses; preserve SSH algorithm @domain patterns."""

        def mailto_repl(m: re.Match) -> str:
            inner = m.group(1)
            inner = self._EMAIL_RE.sub(self._email_replacer, inner)
            return "mailto:" + inner

        s = self._MAILTO_RE.sub(mailto_repl, s)
        return self._EMAIL_RE.sub(self._email_replacer, s)

    def _email_replacer(self, m: re.Match) -> str:
        addr = m.group(0)
        dom = addr.split("@", 1)[-1].lower()
        if dom in self._EMAIL_SKIP_DOMAINS:
            return addr
        return self.DUMMY_EMAIL

    def _fqdn_is_allowlisted(self, host: str) -> bool:
        """True if host is reserved, schema, or other non-tenant DNS name."""
        h = host.lower().rstrip(".")
        if not h or h.startswith("dummy."):
            return True
        for suf in self._FQDN_SAFE_SUFFIXES:
            if h == suf or h.endswith("." + suf):
                return True
        return False

    def _replace_fqdns(self, s: str) -> str:
        """Mask tenant-owned FQDNs; keep only allowlisted infrastructure domains."""

        def repl(m: re.Match) -> str:
            host = m.group(0)
            parts = host.split(".")
            tld = parts[-1].lower()
            # Redfish @odata.type / registry fragments use PascalCase (e.g. Manager.Manager).
            # Upper- and mixed-case DNS names (Kerberos realms, AD domains) end in a DNS suffix.
            if host != host.lower() and tld not in self._DNS_SUFFIX_LABELS:
                return host
            if tld in self._FQDN_SKIP_TLD:
                return host
            if self._fqdn_is_allowlisted(host):
                return host
            return self.DUMMY_FQDN

        return self._FQDN_RE.sub(repl, s)

    def _common_name_looks_like_asset(self, s: str) -> bool:
        """True if HTTPS / cert CommonName likely identifies a specific BMC or host."""
        sl = s.strip()
        if len(sl) < 5 or sl in self._GENERIC_COMMON_NAMES:
            return False
        if "XCC-" in sl or "xcc-" in sl.lower():
            return True
        up = sl.upper()
        if up.startswith("ILO") or "ILO" in up and any(ch.isdigit() for ch in sl):
            return True
        if re.match(r"^[A-Za-z0-9][A-Za-z0-9().-]{10,}$", sl) and any(
            ch.isdigit() for ch in sl
        ):
            return True
        return False

    def _apply_mac_substitution(self, s: str, id_map: Dict[str, str]) -> str:
        return self._MAC_RE.sub(self._mac_repl(id_map), s)

    _COLON_MAC_RE = re.compile(
        r"\b(?:[0-9A-Fa-f]{1,2}:){5}[0-9A-Fa-f]{1,2}\b",
        re.IGNORECASE,
    )
    # Placeholder must not match IPv6 or hostname heuristics.
    _MAC_PLACEHOLDER_SENTINEL = "\ufeff\ufdddMAC-SENTINEL\ufddd\ufeff"

    _MAC_PLACEHOLDER_RE = re.compile(
        r"00:1B:44:AA:([0-9A-Fa-f]{2}):([0-9A-Fa-f]{2})",
        re.IGNORECASE,
    )

    def _protect_dummy_mac_for_ipv6(self, s: str) -> str:
        """Hide every placeholder MAC. The IPv6 pattern also matches 6 colon-separated octets."""
        return self._MAC_PLACEHOLDER_RE.sub(
            lambda m: f"{self._MAC_PLACEHOLDER_SENTINEL}{m.group(1)}{m.group(2)}",
            s,
        )

    def _restore_dummy_mac_after_ipv6(self, s: str) -> str:
        return re.sub(
            re.escape(self._MAC_PLACEHOLDER_SENTINEL) + r"([0-9A-Fa-f]{4})",
            lambda m: f"00:1B:44:AA:{m.group(1)[:2].upper()}:{m.group(1)[2:].upper()}",
            s,
        )

    def _replace_colon_macs_with_dummy(self, s: str, id_map: Dict[str, str]) -> str:
        """Ethernet-style colon MACs before IPv6 pass (IPv6 regex overlaps 6×colon hex)."""
        return self._COLON_MAC_RE.sub(self._mac_repl(id_map), s)

    _CRYPTO_LIST_LEAVES = frozenset(
        {"Ciphers", "MACs", "KexAlgorithms", "HostKeyAlgorithms"}
    )
    _HOSTNAME_LIKE_RE = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+){2,}\b")

    def _replace_hostname_like(self, s: str) -> str:
        """Hyphenated hostname tokens; skip all-hex segments (UUID / GUID fragments)."""

        def repl(m: re.Match) -> str:
            token = m.group(0)
            # DMTF reserves the redfish- prefix for its own schemas (redfish-schema-v1, ...).
            if token.startswith("redfish-"):
                return token
            parts = token.split("-")
            if parts and all(re.fullmatch(r"[0-9a-f]+", p, re.I) for p in parts):
                return token
            return "DUMMY-HostName"

        return self._HOSTNAME_LIKE_RE.sub(repl, s)

    # HPE iLO session ids are <UserName><zero-padded hex>; mask the user name.
    _HPE_SESSION_ID_RE = re.compile(r"^([^/\"?#]+?)(0{6,}[0-9a-f]{8,})$")
    _HPE_SESSION_PATH_RE = re.compile(
        r"(SessionService/Sessions/)([^/\"?#\s]+?)(0{6,}[0-9a-f]{8,})(?=[/\"?#\s]|$)"
    )

    def _session_tail(self, tail: str, id_map: Dict[str, str]) -> str:
        """The hex tail of an HPE session id is an epoch time; swap it for a stable counter."""
        if int(tail, 16) < 0x10000:  # already a counter
            return tail
        return self._stable_placeholder(
            id_map, "session", tail, lambda n: f"{n:0{len(tail)}x}"
        )

    def _mask_session_ids(self, s: str, id_map: Dict[str, str]) -> str:
        return self._HPE_SESSION_PATH_RE.sub(
            lambda m: f"{m.group(1)}DUMMY-User{self._session_tail(m.group(3), id_map)}",
            s,
        )

    def _mask_session_member_id(self, d: dict, id_map: Dict[str, str]) -> None:
        """Mask an HPE session Id that names its own @odata.id (session docs and Members)."""
        odata_id, ident = d.get("@odata.id"), d.get("Id")
        if not isinstance(ident, str) or not isinstance(odata_id, str):
            return
        if "SessionService/Sessions/" not in odata_id and not (
            odata_id == "" and self._HPE_SESSION_ID_RE.match(ident)
        ):
            return
        if odata_id and odata_id.rstrip("/").rsplit("/", 1)[-1] != ident:
            return
        m = self._HPE_SESSION_ID_RE.match(ident)
        if m:
            d["Id"] = "DUMMY-User" + self._session_tail(m.group(2), id_map)

    @staticmethod
    def _is_guid_key(leaf: str) -> bool:
        """True for keys that hold a UUID or GUID (UUID, GPUGUID, OAuth Audience UUID)."""
        low = leaf.lower()
        return "uuid" in low or "guid" in low or low == "audience"

    @staticmethod
    def _json_key_leaf(key: str) -> str:
        """Last dotted segment of an iDRAC-style attribute name."""
        return key.rsplit(".", 1)[-1]

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        s = value.strip()
        if not s:
            return True
        low = s.lower()
        if low in {"none", "null"} or set(s) <= {"0"}:
            return True
        if RedfishSanitizer._is_mac_placeholder(s):
            return True
        # DUMMY-x, DUMMY.example.invalid, DUMMY@example.invalid, idrac-DUMMY-ID-3
        return "DUMMY" in s

    @staticmethod
    def _is_community_list(key: str) -> bool:
        """List fields that hold SNMP community strings (ReadCommunities, CommunityNames)."""
        leaf = key.rsplit(".", 1)[-1]
        return leaf == "CommunityNames" or leaf.endswith("Communities")

    def _assign_dirgroup(self, token: str, id_map: Dict[str, str]) -> str:
        existing = id_map.get(token)
        if existing:
            return existing
        n = 1 + sum(1 for v in id_map.values() if str(v).startswith("dirgroupDUMMY-"))
        placeholder = f"dirgroupDUMMY-{n}"
        id_map[token] = placeholder
        return placeholder

    def _apply_resource_tokens(self, s: str, id_map: Dict[str, str]) -> str:
        """Mask path and log tokens. Does not rewrite IP addresses."""
        if not s or not isinstance(s, str):
            return s

        def dirgroup_repl(m: re.Match) -> str:
            return self._assign_dirgroup(m.group(0), id_map)

        s = self._mask_session_ids(s, id_map)
        s = self._XCC_RE.sub(self.DUMMY_HOSTNAME, s)
        s = self._ILO_RE.sub(self.DUMMY_HOSTNAME, s)
        s = self._BQC_RE.sub(self.DUMMY_SYSTEM_ID, s)
        s = self._DLF_FD_ID_RE.sub(
            lambda m: self._stable_placeholder(
                id_map,
                "entitlement",
                m.group(0),
                lambda n: f"DUMMY-EntitlementId-{n}",
            ),
            s,
        )
        s = self._OME_ID_RE.sub("OME_DUMMY", s)
        s = self._TASK_MONITOR_RE.sub(r"\g<1>DUMMY-Token", s)
        s = self._JOB_ID_RE.sub(
            lambda m: self._stable_placeholder(
                id_map,
                f"job:{m.group(1)}",
                m.group(2),
                lambda n: f"{m.group(1)}_{n:012d}",
            ),
            s,
        )
        s = self._FOD_KEY_ID_RE.sub(
            lambda m: self._stable_placeholder(
                id_map, "fod-key", m.group(0), lambda n: f"DUMMY-FoDKey-{n}"
            ),
            s,
        )
        return self.DIRGROUP_RE.sub(dirgroup_repl, s)

    def _replace_sensitive_patterns(
        self,
        s: str,
        field_name: Optional[str] = None,
        parent_key: Optional[str] = None,
        container_type: Optional[str] = None,
        id_map: Optional[Dict[str, str]] = None,
    ) -> str:
        """Replace PEM, emails, UUID, MAC, IP, hostname-like substrings, and resource tokens."""
        if not s or not isinstance(s, str):
            return s
        if id_map is None:
            id_map = {}
        s = _REPORT_PATH.sub(lambda m: _report_path(m, id_map), s)
        if field_name in self.MAC_SUBSTITUTION_KEYS and self._BARE_MAC12_RE.match(
            s.strip()
        ):
            if self._is_mac_placeholder(s):
                return s
            return self._assign_mac(id_map, s)
        s = self._mask_session_ids(s, id_map)
        s = self._replace_pem_blocks(s)
        s = self._SSH_PUBLIC_KEY_RE.sub("ssh-ed25519 DUMMY-Key", s)
        s = self._DN_RE.sub(self.DUMMY_DN, s)
        s = self._replace_qualified_names(s)
        s = self._replace_emails_in_string(s)
        s = self._replace_uris(s)
        s = self._replace_fqdns(s)
        s = self._replace_identifier_forms(s, id_map)
        # All UUID-shaped tokens (instance ids, OAuth audience, UEFI path GUIDs, etc.)
        s = self._UUID_RE.sub(self._uuid_repl(id_map), s)
        s = self._UNDERSCORE_GUID_RE.sub(self.DUMMY_UUID.replace("-", "_"), s)
        s = self._COLON_HEX_LONG_RE.sub(self.DUMMY_MAC, s)
        s = self._apply_mac_substitution(s, id_map)
        s = self._replace_colon_macs_with_dummy(s, id_map)
        if field_name in self.MAC_SUBSTITUTION_KEYS:
            s = self._apply_mac_substitution(s, id_map)
        s = self._protect_dummy_mac_for_ipv6(s)
        s = self._COMPRESSED_IPV6_RE.sub(self.DUMMY_IPV6, s)
        s = self._IPV6_LIKE_RE.sub(self._ipv6_like_repl, s)
        s = self._restore_dummy_mac_after_ipv6(s)
        if not self._skip_ipv4_substitution(field_name, parent_key, container_type, s):
            s = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", self.DUMMY_IPV4, s)
        s = self._replace_hostname_like(s)
        s = self._apply_resource_tokens(s, id_map)
        # Hostname pass can split dummy UUID; normalize any remaining uuid tokens.
        s = self._UUID_RE.sub(self._uuid_repl(id_map), s)
        return s

    def _ipv6_like_repl(self, m: re.Match) -> str:
        """IPv6-shaped token, except a clock time such as 08:30:15."""
        if self._CLOCK_TIME_RE.fullmatch(m.group(0)):
            return m.group(0)
        return self.DUMMY_IPV6

    def _replace_identifier_forms(self, s: str, id_map: Dict[str, str]) -> str:
        """Serial, MAC and host forms that only appear inside free text or paths."""

        def path_mac(m: re.Match) -> str:
            bare = self._assign_mac(id_map, m.group(2)).replace(":", "")
            return m.group(1) + bare

        def ilo_mac(m: re.Match) -> str:
            bare = self._assign_mac(id_map, m.group(2)).replace(":", "").lower()
            return m.group(1) + bare

        def byte_run(m: re.Match) -> str:
            octets = re.findall(r"[0-9A-Fa-f]{2}", m.group(0))
            if len(octets) != 6:
                return self.DUMMY_MAC
            return self._assign_mac(id_map, "".join(octets))

        s = self._MAC_IN_PATH_RE.sub(path_mac, s)
        s = self._ILO_MAC_NAME_RE.sub(ilo_mac, s)
        s = self._BYTE_RUN_MAC_RE.sub(byte_run, s)
        s = self._SN_PAREN_RE.sub(r"\g<1>DUMMY-Serial)", s)
        s = self._SN_HASH_RE.sub(r"\g<1>DUMMY-Serial", s)
        s = self._LENOVO_BOOT_SN_RE.sub(r"\g<1>DUMMY-Serial\g<2>", s)
        s = self._INTEL_BOOT_SN_RE.sub(r"\g<1>DUMMY-Serial\g<2>", s)
        s = self._HPE_LOGICAL_DRIVE_RE.sub(r"\g<1>DUMMYCONTROLLER\g<2>", s)
        s = self._IKVM_URI_RE.sub("/redfish/DUMMY-IKVM.IKVM", s)
        s = self._mask_log_users(s)
        return self._HSTNAME_KV_RE.sub("HstName=" + self.DUMMY_HOSTNAME, s)

    def _log_users(self, text: Any) -> set:
        """Accounts named in a log message that are not on the allowlist."""
        if not isinstance(text, str):
            return set()
        found = set()
        for pattern in self.USER_PATTERNS:
            for m in pattern.finditer(text):
                user = m.group(1).rstrip(".,;")
                if (
                    user
                    and user not in self.USER_ALLOWLIST
                    and not user.startswith("DUMMY")
                ):
                    found.add(user)
        return found

    def _mask_log_users(self, s: str) -> str:
        for pattern in self.USER_PATTERNS:
            s = pattern.sub(lambda m: self._swap_user(m), s)
        return s

    def _swap_user(self, m: re.Match) -> str:
        user = m.group(1).rstrip(".,;")
        if not user or user in self.USER_ALLOWLIST or user.startswith("DUMMY"):
            return m.group(0)
        start, end = m.span(1)
        offset = m.start()
        text = m.group(0)
        return text[: start - offset] + self.DUMMY_USER + text[end - offset :]

    # Values of settings whose names end like secrets (EnableSNMPv3Passphrase, StrongPassword).
    _SETTING_VALUES = frozenset(
        {"Enabled", "Disabled", "True", "False", "Yes", "No", "On", "Off", "Done"}
    )

    def _mapped_leaf_placeholder(self, leaf: str, value: str = "") -> Optional[str]:
        """Placeholder for a leaf whose whole value is always replaced."""
        groups = (
            (self._HOST_LEAVES, self.DUMMY_HOSTNAME),
            (self._ACCOUNT_LEAVES, self.DUMMY_USER),
            (self._SECRET_LEAVES, self.DUMMY_SECRET),
            (self._COMMUNITY_LEAVES, self.DUMMY_COMMUNITY),
            (self._WWN_LEAVES, self.DUMMY_WWN),
        )
        for leaves, placeholder in groups:
            if leaf in leaves:
                return placeholder
        if leaf.endswith(self._SECRET_SUFFIXES) and value not in self._SETTING_VALUES:
            return self.DUMMY_SECRET
        if leaf.endswith(self._PHONE_SUFFIXES):
            return "DUMMY-Phone"
        if leaf in self._SITE_LEAVES:
            return f"DUMMY-{leaf}"
        if leaf == "LicenseKey":
            return "DUMMY-LicenseKey"
        if leaf == "ArchitectureId":
            # The schema requires space-separated hex bytes, so a DUMMY- string would not validate.
            return "00 00 00 00 00 00 00 00"
        if leaf in self._DEVICE_ID_LEAVES or leaf in self._OPAQUE_LEAVES:
            return f"DUMMY-{leaf}"
        return None

    def _sanitize_embedded_json(
        self, value: str, key: str, id_map: Dict[str, str]
    ) -> Optional[str]:
        """Sanitize JSON stored inside a string (Supermicro LicenseManager). None if not JSON."""
        try:
            inner = json.loads(value)
        except ValueError:
            return None
        if not isinstance(inner, (dict, list)):
            return None
        cleaned = self._sanitize_impl(inner, parent_key=key, id_map=id_map)
        if cleaned == inner:
            return value
        return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))

    def _sanitize_string(
        self,
        key: str,
        value: str,
        parent_key: Optional[str],
        container_type: Optional[str],
        id_map: Dict[str, str],
    ) -> str:
        """Apply leaf rules, then the substring pass, to one string field."""
        leaf = self._json_key_leaf(key)
        stripped = value.strip()
        # JsonSchemaFile.Schema is a type locator (#odata.v4_0_1.odata), never tenant data.
        if key == "Schema" and re.fullmatch(r"#[\w.-]+", stripped):
            return value
        # SSH algorithm lists (diffie-hellman-group14-sha256, hmac-sha2-256, ...) name
        # protocols, not hosts, and hold no tenant data.
        if leaf in self._CRYPTO_LIST_LEAVES and re.fullmatch(
            r"[A-Za-z0-9@._,\- ]+", stripped
        ):
            return value
        if stripped[:1] in ("{", "["):
            embedded = self._sanitize_embedded_json(value, key, id_map)
            if embedded is not None:
                return embedded
        replacement = None
        if (
            stripped
            and stripped.lower() not in {"none", "null"}
            and (
                leaf == "CertCommonName"
                or (
                    leaf.endswith("CommonName")
                    and self._common_name_looks_like_asset(value)
                )
            )
        ):
            replacement = self.DUMMY_COMMON_NAME
        elif not self._is_placeholder(value):
            mapped = self._mapped_leaf_placeholder(leaf, stripped)
            if mapped is not None:
                replacement = mapped
            elif leaf == "Location" and parent_key in self._SNMP_LOCATION_PARENTS:
                replacement = "DUMMY-Location"
            elif parent_key == "PostalAddress" and leaf != "Country":
                replacement = f"DUMMY-{leaf}"
            elif parent_key == "Placement" and leaf in self._PLACEMENT_LEAVES:
                replacement = f"DUMMY-{leaf}"
            elif (
                self._CERT_NAME_LEAF_RE.match(leaf)
                or (
                    parent_key in ("Subject", "Issuer")
                    and leaf in self._CERT_NAME_FIELDS
                )
            ) and self._site_certificate_name(stripped):
                replacement = f"DUMMY-{leaf}"
            elif leaf == "Fingerprint" and stripped != self.DUMMY_MAC:
                replacement = "DUMMY-Fingerprint"
            elif leaf == "CertificateString" and self._BARE_BASE64_RE.fullmatch(
                stripped
            ):
                replacement = self.DUMMY_PEM_BLOCK
            elif leaf == "Identifier" and container_type and "FoDKey" in container_type:
                # Machine type plus serial: the exact input to Lenovo's warranty lookup.
                replacement = self._stable_placeholder(
                    id_map,
                    "fod-identifier",
                    stripped,
                    lambda n: f"DUMMY-Identifier-{n}",
                )
            elif leaf == "URI" and parent_key == "IKVM" and ".IKVM" in stripped:
                replacement = "/redfish/DUMMY-IKVM.IKVM"
            elif (
                leaf in self._SWITCH_PORT_LEAVES
                and stripped not in self._SWITCH_STATUS_VALUES
                and not self._COLON_MAC_RE.fullmatch(stripped)
            ):
                replacement = "DUMMY-Port"
            elif leaf in self._RAW_MAC_LEAVES and self._RAW_MAC_RE.match(stripped):
                if len(stripped) == 12 and not self._is_mac_placeholder(stripped):
                    replacement = self._assign_mac(id_map, stripped)
                elif self._is_mac_placeholder(stripped):
                    replacement = stripped
                else:
                    replacement = self.DUMMY_MAC
            elif leaf == "PartNumber" and self._SN_PARTNUMBER_RE.match(stripped):
                replacement = "DUMMY-PartNumber"
        if replacement is None and (
            key == "Name"
            and stripped
            and re.match(r"^[a-z][a-z0-9-]{4,}$", value)
            and "-" in value
        ):
            replacement = self.DUMMY_HOSTNAME
        if (
            replacement is None
            and self._is_guid_key(leaf)
            and self._UNDASHED_GUID_RE.match(stripped)
        ):
            # Undashed GUIDs: dashed forms are caught by the generic UUID pass.
            replacement = self.DUMMY_UUID.replace("-", "")
        if (
            replacement is None
            and leaf in self._STORAGE_ID_LEAVES
            and not self._is_placeholder(value)
            and not self._STORAGE_ID_PLACEHOLDER_RE.fullmatch(stripped)
        ):
            replacement = self._stable_placeholder(
                id_map,
                f"storage:{leaf}",
                stripped,
                lambda n: self._storage_id_placeholder(stripped, leaf, n),
            )
        if (
            replacement is None
            and self._mask_serial_value(key)
            and not self._is_placeholder(value)
        ):
            replacement = self._stable_placeholder(
                id_map,
                f"serial:{key}",
                value,
                lambda n: f"DUMMY-{key}-{n}",
            )
        if replacement is None:
            replacement = self._replace_sensitive_patterns(
                value,
                field_name=key,
                parent_key=parent_key,
                container_type=container_type,
                id_map=id_map,
            )
        return replacement

    def _sanitize_community_list(
        self, value: list, key: str, id_map: Dict[str, str]
    ) -> list:
        """Replace community strings and recurse into nested values."""
        items = []
        for item in value:
            if (
                isinstance(item, str)
                and item.strip()
                and not self._is_placeholder(item)
            ):
                items.append(self.DUMMY_COMMUNITY)
            elif isinstance(item, (dict, list)):
                items.append(self._sanitize_impl(item, parent_key=key, id_map=id_map))
            else:
                items.append(item)
        return items

    def _sanitize_message_args(
        self, value: list, key: str, id_map: Dict[str, str]
    ) -> list:
        """Sanitize log message arguments."""
        args = []
        for item in value:
            if isinstance(item, str):
                args.append(self._replace_sensitive_patterns(item, id_map=id_map))
            elif isinstance(item, (dict, list)):
                args.append(self._sanitize_impl(item, parent_key=key, id_map=id_map))
            else:
                args.append(item)
        return args

    def _sanitize_list(self, key: str, value: list, id_map: Dict[str, str]) -> Any:
        """Sanitize one list-valued property."""
        if self._is_community_list(key):
            return self._sanitize_community_list(value, key, id_map)
        if key == "MessageArgs":
            return self._sanitize_message_args(value, key, id_map)
        if key in self._HOST_LIST_KEYS:
            value = [self._host_list_item(i) for i in value]
        if key == "Bytes" and all(isinstance(i, int) for i in value):
            # A signed Lenovo FoD key: its bytes spell out the machine type and serial.
            return []
        return self._sanitize_impl(value, parent_key=key, id_map=id_map)

    _IP_LIKE_RE = re.compile(r"^[0-9A-Fa-f.:]+$")

    def _host_list_item(self, item: Any) -> Any:
        """A host name in an NTP or DNS server list. Addresses and URIs go to later passes."""
        if not isinstance(item, str):
            return item
        s = item.strip()
        if (
            self._is_placeholder(s)
            or s == "localhost"
            or self._IP_LIKE_RE.match(s)
            or "://" in s
            or self._fqdn_is_allowlisted(s)
        ):
            return item
        return self.DUMMY_FQDN

    def _sanitize_dict(
        self,
        sanitized: dict,
        parent_key: Optional[str],
        id_map: Dict[str, str],
    ) -> None:
        """Sanitize the properties of one object in place."""
        container_type = self._odata_container_type(sanitized)
        _mask_certificate_fields(sanitized)
        resource = sanitized.get("@odata.id")
        if isinstance(resource, str) and (report := _REPORT_PATH.search(resource)):
            if report.end() == len(resource) and report[2] not in _STANDARD_REPORTS:
                alias = _report_path(report, id_map).rsplit("/", 1)[-1]
                for field in ("Id", "Name", "Description"):
                    if sanitized.get(field):
                        sanitized[field] = alias
        self._mask_session_member_id(sanitized, id_map)
        log_users = self._log_users(sanitized.get("Message"))
        for key in list(sanitized.keys()):
            value = sanitized[key]
            if (
                key in self._COORDINATE_LEAVES
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                sanitized[key] = None
            elif isinstance(value, str):
                sanitized[key] = self._sanitize_string(
                    key, value, parent_key, container_type, id_map
                )
            elif isinstance(value, list):
                sanitized[key] = self._sanitize_list(key, value, id_map)
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_impl(
                    value, parent_key=key, id_map=id_map
                )
        args = sanitized.get("MessageArgs")
        if log_users and isinstance(args, list):
            # The user named in Message is usually repeated as an argument.
            sanitized["MessageArgs"] = [
                self.DUMMY_USER if isinstance(a, str) and a in log_users else a
                for a in args
            ]

    def _sanitize_sequence(
        self,
        sanitized: list,
        parent_key: Optional[str],
        id_map: Dict[str, str],
    ) -> None:
        """Sanitize a bare list, such as AssociatedNetworkAddresses."""
        for index, item in enumerate(sanitized):
            if isinstance(item, str) and item.strip()[:1] in ("{", "["):
                # JSON stored in a list item (Supermicro LicenseManager Licenses[]).
                embedded = self._sanitize_embedded_json(item, parent_key or "", id_map)
                if embedded is not None:
                    sanitized[index] = embedded
                    continue
            if isinstance(item, str):
                leaf = self._json_key_leaf(parent_key) if parent_key else ""
                if (
                    leaf
                    and self._is_guid_key(leaf)
                    and self._UNDASHED_GUID_RE.match(item.strip())
                ):
                    sanitized[index] = self.DUMMY_UUID.replace("-", "")
                    continue
                sanitized[index] = self._replace_sensitive_patterns(
                    item,
                    field_name=parent_key,
                    parent_key=parent_key,
                    container_type=None,
                    id_map=id_map,
                )
            elif isinstance(item, (dict, list)):
                sanitized[index] = self._sanitize_impl(
                    item, parent_key=parent_key, id_map=id_map
                )

    def _sanitize_impl(
        self,
        data: Any,
        parent_key: Optional[str] = None,
        id_map: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Sanitize sensitive information from the response data."""
        if id_map is None:
            id_map = {}
        sanitized = json.loads(json.dumps(data))

        if isinstance(sanitized, dict):
            self._sanitize_dict(sanitized, parent_key, id_map)
        elif isinstance(sanitized, list):
            self._sanitize_sequence(sanitized, parent_key, id_map)
        return sanitized

    def sanitize_data(
        self,
        data: Any,
        parent_key: Optional[str] = None,
        id_map: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Sanitize one Redfish JSON value."""
        if id_map is None:
            id_map = {}
        return self._sanitize_impl(data, parent_key=parent_key, id_map=id_map)

    def apply_resource_tokens(
        self, text: str, id_map: Optional[Dict[str, str]] = None
    ) -> str:
        """Mask BQC, XCC, iLO, and dirgroup tokens. Does not rewrite IP addresses."""
        if id_map is None:
            id_map = {}
        return self._apply_resource_tokens(text, id_map)


_SANITIZER = RedfishSanitizer()


def build_dirgroup_id_map(tokens: Iterable[str]) -> Dict[str, str]:
    """Sorted, stable placeholders so distinct directory-group ids do not collide."""
    return {
        tok: f"dirgroupDUMMY-{i}" for i, tok in enumerate(sorted(set(tokens)), start=1)
    }


def sanitize_redfish(
    data: Any,
    *,
    id_map: Mapping[str, str] | None = None,
    parent_key: str | None = None,
) -> Any:
    """Sanitize a Redfish JSON value. Shared by snapshots and fixtures rewrites."""
    mapping: Dict[str, str] = dict(id_map) if id_map is not None else {}
    # Mutate the caller's dict when they passed one, so dirgroup assignments stick.
    if isinstance(id_map, dict):
        mapping = id_map
    return _SANITIZER.sanitize_data(data, parent_key=parent_key, id_map=mapping)


def sanitize_path(path: str, *, id_map: Mapping[str, str] | None = None) -> str:
    """Sanitize a resource path the way its ``@odata.id`` is sanitized in the body.

    *path* is a URL path (``/redfish/v1/...``) or a mockup file path relative to the tree
    (``redfish/v1/.../index.json``). Keeping the two in step means a UUID, address or host
    name used as a resource Id is removed from the directory name too, and the file stays
    where the masked links point.
    """
    if not isinstance(path, str):
        return path
    mapping: Dict[str, str] = dict(id_map) if id_map is not None else {}
    if isinstance(id_map, dict):
        mapping = id_map
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)
        query = "?" + query
    suffix = ""
    if path.endswith("/index.json") or path == "index.json":
        path, suffix = path[: -len("index.json")], "index.json"
    lead = "" if path.startswith("/") else "/"
    body = path.rstrip("/") if suffix else path
    out = _SANITIZER._replace_sensitive_patterns(
        lead + body, field_name="@odata.id", id_map=mapping
    )
    out = out[len(lead) :]
    if suffix:
        out = (out + "/" if out else "") + suffix
    return out + query


def sanitize_resource_tokens(
    text: str,
    *,
    id_map: Mapping[str, str] | None = None,
) -> str:
    """Mask BQC, XCC, iLO, and dirgroup tokens in a URL or path. Does not rewrite IPs."""
    if not isinstance(text, str):
        return text
    mapping: Dict[str, str] = dict(id_map) if id_map is not None else {}
    if isinstance(id_map, dict):
        mapping = id_map
    return _SANITIZER.apply_resource_tokens(text, mapping)


# Separators that real identifiers are written with (serial 7FS-XYZ, MAC 00:1B:44, UUID-like).
_SEP_CHARS_RE = re.compile(r"[\s:\-._]")
_SEP_BETWEEN = r"[\s:\-._]*"
_MIN_IDENTIFIER_LEN = 6
_MAC_MARK = "\x00mac"
_ENCODED_PLACEHOLDER = "DUMMY-Encoded"


def _identifier_key(s: str) -> str:
    """Upper-case form with separators removed; the comparison key for identifier matching."""
    return _SEP_CHARS_RE.sub("", s).upper()


# The sanitizer's own stand-ins. Earlier runs leave them in the captures, so they must never
# be collected as identifiers and masked a second time.
_DUMMY_IDENTIFIER_KEYS = frozenset(
    _identifier_key(v)
    for v in (
        RedfishSanitizer.DUMMY_MAC,
        RedfishSanitizer.DUMMY_WWN,
        RedfishSanitizer.DUMMY_UUID,
        RedfishSanitizer.DUMMY_IPV4,
        RedfishSanitizer.DUMMY_IPV6,
    )
)
_MAC_SHAPED_RE = re.compile(r"[0-9A-F]{12}")
# Keys whose values name the customer or an account. Taken as identifiers so the same text
# is removed from log messages and subscriptions, where no key rule can see it.
_NAME_LEAVES = frozenset(
    {
        "RecipientName",
        "ContactName",
        "ContactPerson",
        "SysContact",
        "LoginName",
        "Account",
        "AccountName",
    }
)
_NAME_STOPLIST = frozenset(
    {_identifier_key(u) for u in RedfishSanitizer.USER_ALLOWLIST}
    | {
        "LOCALHOST",
        "DEFAULT",
        "NONE",
        "NULL",
        "UNKNOWN",
        "NOTSPECIFIED",
        "NOTAVAILABLE",
    }
)

# Places where a serial, tag or MAC is still written out in a string, after the key rules have
# run on the same capture. Group 1 (when present) is the identifier.
_IDENTIFIER_TEXT_RES = (
    re.compile(r"uefi-U\d+-([A-Za-z0-9]+)"),  # iSCSI initiator names
    re.compile(r"HPE_([A-Za-z0-9]+)_"),  # HPE backup file names
    re.compile(r"idrac-([A-Za-z0-9]+)", re.IGNORECASE),  # DNSRacName, certificate CN
    re.compile(r"\bST: ([A-Za-z0-9]+)"),  # Dell LCD display
    re.compile(r"\bBQC[0-9A-Z]{6,}\b"),  # Intel system serial in @odata.id
    re.compile(r"\bSN#\s*([A-Z0-9]{7,10})\b"),  # Lenovo log serial
    re.compile(r"\(SN: ([^)]+)\)"),  # Lenovo component serial in log text
    re.compile(r"\bHstName=([^,\s]+)"),  # Lenovo platform log host name
    re.compile(r"XCC-[A-Za-z0-9]+-([A-Za-z0-9]+)"),  # Lenovo XCC name, also in hex
    re.compile(r"MAC\(([0-9A-Fa-f]{12}),"),  # UEFI device path MAC
    re.compile(r"\bilo-([0-9A-Fa-f]{12})\b", re.IGNORECASE),  # HPE ESKM account name
    re.compile(r"\)\s+([A-Z0-9]{10,20})\s+-"),  # Lenovo boot-order drive serial
    re.compile(r"^UEFI \S+ \S+ ([A-Z0-9]{10,})\s*$"),  # Intel boot-order drive serial
    re.compile(r"\b[0-9A-F]{8}([A-Z0-9]{14}) [0-9A-F]{4}\b"),  # HPE default drive name
)
_HEX_BLOB_RE = re.compile(r"^(?:0x)?(?:[0-9A-Fa-f]{2})+$")


def _ascii_runs(data: bytes) -> list:
    """Printable, space-free runs in binary data (SNMP EngineIDs hide serials this way)."""
    runs, current = [], []
    for byte in data:
        if 0x21 <= byte <= 0x7E:
            current.append(chr(byte))
        elif current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))
    return runs


def _identifier_candidates(key: Optional[str], value: str) -> set:
    """Identifier candidates from one string value (raw, not yet sanitized)."""
    found: set = set()
    leaf = RedfishSanitizer._json_key_leaf(key) if key else ""
    if leaf in RedfishSanitizer.MAC_SUBSTITUTION_KEYS or leaf in (
        "NodeID",
        "UniqueID",
    ):
        found.add(value.strip())
    if leaf == "ExpressServiceCode" and value.strip().isdigit():
        # Dell Express Service Code is the service tag read as a base-36 integer.
        n, digits = int(value.strip()), []
        while n:
            n, rem = divmod(n, 36)
            digits.append("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"[rem])
        found.add("".join(reversed(digits)))
    if any(tag in leaf for tag in ("EngineID", "EngineId", "ArchitectureId")):
        hex_text = re.sub(r"\s", "", value)
        if _HEX_BLOB_RE.match(hex_text):
            try:
                blob = bytes.fromhex(re.sub(r"^0x", "", hex_text, flags=re.IGNORECASE))
            except ValueError:
                blob = b""
            for run in _ascii_runs(blob):
                found.add(run)
                for pattern in _IDENTIFIER_TEXT_RES:
                    for m in pattern.finditer(run):
                        found.add(m.group(m.lastindex or 0))
    for pattern in _IDENTIFIER_TEXT_RES:
        for m in pattern.finditer(value):
            found.add(m.group(m.lastindex or 0))
    return found


def collect_identifiers(data: Any) -> set:
    """Real serial, tag, MAC, customer and account values in one Redfish document.

    Call it on the raw document, before sanitizing. Values come from identifier keys, from
    encodings the key rules cannot see (hex EngineIDs, base-36 service codes), from
    identifier-shaped text, and from the keys that name the customer or an account. The
    result is searched for in every string, key, path and metadata value of the same capture.
    """
    serials: set = set()
    names: set = set()

    def is_identifier_key(key: Optional[str]) -> bool:
        if not key:
            return False
        leaf = RedfishSanitizer._json_key_leaf(key)
        return (
            _SANITIZER._mask_serial_value(leaf)
            or leaf in ("NodeID", "UniqueID")
            or key in RedfishSanitizer.MAC_SUBSTITUTION_KEYS
        )

    def visit(obj: Any, key: Optional[str]) -> None:
        if isinstance(obj, dict):
            kind = obj.get("@odata.type")
            ident = obj.get("Identifier")
            if isinstance(kind, str) and "FoDKey" in kind and isinstance(ident, str):
                serials.add(ident.strip())
            for child_key, child in obj.items():
                visit(child, child_key)
        elif isinstance(obj, list):
            for item in obj:
                visit(item, key)
        elif isinstance(obj, str):
            if RedfishSanitizer._is_placeholder(obj):
                return
            if is_identifier_key(key):
                serials.add(obj.strip())
            if key and RedfishSanitizer._json_key_leaf(key) in _NAME_LEAVES:
                names.add(obj.strip())
            serials.update(_identifier_candidates(key, obj))

    visit(data, None)

    def usable(v: str) -> bool:
        k = _identifier_key(v)
        return (
            len(k) >= _MIN_IDENTIFIER_LEN
            and k not in _DUMMY_IDENTIFIER_KEYS
            and not v.strip().startswith("DUMMY")
            and k.isalnum()
        )

    return {v for v in serials if usable(v) and any(c.isdigit() for c in v)} | {
        v for v in names if usable(v) and _identifier_key(v) not in _NAME_STOPLIST
    }


_HEX_RUN_RE = re.compile(
    r"(?<![0-9A-Za-z])(?:0[xX])?(?:[0-9A-Fa-f]{2}){6,}(?![0-9A-Za-z])"
    r"|(?<![0-9A-Za-z])(?:[0-9A-Fa-f]{2} ){5,}[0-9A-Fa-f]{2}(?![0-9A-Za-z])"
)
_B64_RUN_RE = re.compile(
    r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/=])"
)


class IdentifierMasker:
    """Replace collected identifiers wherever they reappear, in any separator or encoding.

    Each identifier gets one placeholder (``DUMMY-ID-<n>``), numbered in sorted order so the
    same capture always produces the same output. A 6-octet MAC keeps a MAC shape and shares
    the ``mac`` entries of *id_map* with the field pass, so one address stays one value.
    Matching ignores case and separators, so ``7FS-ABC123`` and ``7fs abc123`` are both
    found. The hex-ASCII form is searched too, and hex or base64 runs are decoded and
    replaced whole when the decoded text holds one.
    """

    def __init__(
        self,
        identifiers: Iterable[str],
        id_map: Optional[Dict[str, str]] = None,
    ) -> None:
        self._id_map = id_map if id_map is not None else {}
        self._forms: Dict[str, str] = {}
        for i, value in enumerate(sorted(set(identifiers)), start=1):
            key = _identifier_key(value)
            # A MAC must stay MAC-shaped or schema validation of the field fails.
            placeholder = (
                _MAC_MARK if _MAC_SHAPED_RE.fullmatch(key) else f"DUMMY-ID-{i}"
            )
            self._forms.setdefault(key, placeholder)
            self._forms.setdefault(value.encode().hex().upper(), placeholder)
        if not self._forms:
            self._pattern = None
            return
        alternatives = []
        for form in sorted(self._forms, key=len, reverse=True):
            alternatives.append(_SEP_BETWEEN.join(re.escape(ch) for ch in form))
        self._pattern = re.compile("|".join(alternatives), re.IGNORECASE)

    def mask(self, text: str) -> str:
        if self._pattern is None or not text:
            return text
        text = _HEX_RUN_RE.sub(self._mask_hex_run, text)
        if len(text) >= 24:
            text = _B64_RUN_RE.sub(self._mask_b64_run, text)
        return self._pattern.sub(self._replacement, text)

    def mask_key(self, key: str) -> str:
        """Mask a dictionary key without the decode pass."""
        if self._pattern is None or not key:
            return key
        return self._pattern.sub(self._replacement, key)

    def _decoded_hit(self, blob: bytes) -> bool:
        return len(blob) >= 4 and bool(self._pattern.search(blob.decode("latin-1")))

    def _mask_hex_run(self, m: re.Match) -> str:
        digits = re.sub(r"^0[xX]|\s", "", m.group(0))
        try:
            blob = bytes.fromhex(digits)
        except ValueError:
            return m.group(0)
        return _ENCODED_PLACEHOLDER if self._decoded_hit(blob) else m.group(0)

    def _mask_b64_run(self, m: re.Match) -> str:
        run = m.group(0)
        try:
            blob = base64.b64decode(run + "=" * (-len(run) % 4), validate=True)
        except ValueError:
            return run
        return _ENCODED_PLACEHOLDER if self._decoded_hit(blob) else run

    def _replacement(self, m: re.Match) -> str:
        key = _identifier_key(m.group(0))
        placeholder = self._forms[key]
        if placeholder != _MAC_MARK:
            return placeholder
        if _MAC_SHAPED_RE.fullmatch(key):
            colon = RedfishSanitizer._assign_mac(self._id_map, key)
            return colon if _SEP_CHARS_RE.search(m.group(0)) else colon.replace(":", "")
        return RedfishSanitizer.DUMMY_MAC


def map_etags(data: Any, fn) -> int:
    """Replace every ``@odata.etag`` value in a document with ``fn(old)``. Returns the count."""
    count = 0
    if isinstance(data, dict):
        for key in data:
            if key == "@odata.etag":
                data[key] = fn(data[key])
                count += 1
            else:
                count += map_etags(data[key], fn)
    elif isinstance(data, list):
        for item in data:
            count += map_etags(item, fn)
    return count
