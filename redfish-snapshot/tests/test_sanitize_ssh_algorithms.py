# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""SSH algorithm lists name protocols, so the hostname rule must not mask them."""

from redfish_snapshot.sanitize import sanitize_redfish


def test_dell_ssh_algorithm_lists_are_kept():
    attrs = {
        "SSHCrypto.1.Ciphers": "chacha20-poly1305@openssh.com,aes128-ctr,aes256-gcm@openssh.com",
        "SSHCrypto.1.HostKeyAlgorithms": "ecdsa-sha2-nistp256,rsa-sha2-512,ssh-ed25519",
        "SSHCrypto.1.KexAlgorithms": "curve25519-sha256,diffie-hellman-group14-sha256",
        "SSHCrypto.1.MACs": "hmac-sha2-256-etm@openssh.com,umac-128@openssh.com",
    }
    assert sanitize_redfish({"Attributes": dict(attrs)}) == {"Attributes": attrs}


def test_hostname_like_values_elsewhere_are_still_masked():
    out = sanitize_redfish({"Name": "rack12-row3-bmc"})
    assert out["Name"] != "rack12-row3-bmc"
