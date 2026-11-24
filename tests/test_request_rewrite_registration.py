# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Cold-start registration for request rewrite rules (see request_rewrites.py)."""

from __future__ import annotations

import sys


def test_get_request_rewrite_loads_chassis_rules_on_empty_registry():
    # Use a subprocess so ``_rules`` is empty (no prior normalizers import).
    code = r"""
import normalizers.request_rewrites as rr
r_hpe = rr.get_request_rewrite(
    "HPE",
    "/redfish/v1/Chassis/1/NetworkAdapters/x/Ports",
    client=None,
)
assert r_hpe is not None, "HPE Ports rewrite should register"
r_lenovo = rr.get_request_rewrite(
    "Lenovo",
    "/redfish/v1/Chassis/1/NetworkAdapters/slot-1/Ports",
    client=None,
)
assert r_lenovo is not None, "Lenovo Ports rewrite should register"
# NetworkPorts is deprecated and is not rewritten for Lenovo.
assert rr.get_request_rewrite(
    "Lenovo",
    "/redfish/v1/Chassis/1/NetworkAdapters/slot-1/NetworkPorts",
    client=None,
) is None
vendors = {x.vendor for x in rr._rules}
assert "HPE" in vendors
assert "Lenovo" in vendors
assert len(rr._rules) >= 3
"""
    proc = __import__("subprocess").run(
        [sys.executable, "-c", code],
        cwd=__import__("pathlib").Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
