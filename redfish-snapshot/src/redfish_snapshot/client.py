# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Redfish HTTP client with an optional Host header."""

import warnings

import urllib3
from redfish.rest.v1 import HttpClient as RedfishHttpClient


class HttpClient(RedfishHttpClient):
    """Redfish HttpClient that can send a custom ``Host`` header (tunnel/VIP/SNI-style setups)."""

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        base_url,
        username=None,
        password=None,
        default_prefix="/redfish/v1/",
        sessionkey=None,
        capath=None,
        cafile=None,
        timeout=None,
        max_retry=None,
        proxies=None,
        check_connectivity=True,
        https_adapter=None,
        host_header=None,
        show_tls_warnings=False,
    ):
        # BMCs usually present self-signed certificates, so this client does not verify
        # them, and urllib3 would warn on every request. Hide that warning unless the
        # caller asks for it. Note: the redfish library already hides it process-wide
        # when it is imported, so the opt-in works by adding a filter in front of that.
        if show_tls_warnings:
            warnings.filterwarnings(
                "default", category=urllib3.exceptions.InsecureRequestWarning
            )
        else:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        defer_root = bool(host_header)
        super().__init__(
            base_url=base_url,
            username=username,
            password=password,
            default_prefix=default_prefix,
            sessionkey=sessionkey,
            capath=capath,
            cafile=cafile,
            timeout=timeout,
            max_retry=max_retry,
            proxies=proxies,
            check_connectivity=(False if defer_root else check_connectivity),
            https_adapter=https_adapter,
        )
        if host_header:
            self._session.headers["Host"] = host_header
        if defer_root and check_connectivity:
            self.get_root_object()
            try:
                self.login_url = self.root.Links.Sessions["@odata.id"]
            except (KeyError, AttributeError):
                self.login_url = "/redfish/v1/SessionService/Sessions"
