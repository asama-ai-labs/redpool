# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""The proxy tells a BMC's own name from a platform name through a registered marker."""

import normalizers  # noqa: F401  (importing registers the vendor markers)
from normalizers.service_root import product_names_bmc
from redpool.proxy import RedfishProxy


def test_dell_idrac_product_names_the_bmc() -> None:
    assert product_names_bmc("Integrated Dell Remote Access Controller")
    assert product_names_bmc("  integrated dell REMOTE ACCESS CONTROLLER 9 ")


def test_platform_names_are_not_bmc_names() -> None:
    assert not product_names_bmc("PowerEdge R760")
    assert not product_names_bmc("")


def test_proxy_uses_the_registered_markers() -> None:
    assert not RedfishProxy._product_is_server_model(
        "Integrated Dell Remote Access Controller"
    )
    assert not RedfishProxy._product_is_server_model("unknown")
    assert RedfishProxy._product_is_server_model("ProLiant DL380 Gen10")
