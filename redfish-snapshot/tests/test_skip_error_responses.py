# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""A non-2xx response is not a resource: it is neither saved nor listed as collected."""

import asyncio
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from redfish_snapshot.main import RedfishCloner


def _cloner(out: str, responses: dict) -> RedfishCloner:
    with patch("redfish_snapshot.main.HttpClient") as mock_http:
        client = MagicMock()
        client.get.side_effect = lambda url: responses[url]
        mock_http.return_value = client
        return RedfishCloner(
            host="127.0.0.1",
            username="u",
            password="p",
            output_path=out,
            sanitize=False,
        )


def test_error_responses_are_skipped_and_not_listed():
    ok = SimpleNamespace(status=200, dict={"Id": "1"})
    missing = SimpleNamespace(
        status=404, dict={"error": {"code": "Base.1.5.0.GeneralError"}}
    )
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "out")
        cloner = _cloner(out, {"/redfish/v1/Good": ok, "/redfish/v1/Gone": missing})

        asyncio.run(cloner.process_url("/redfish/v1/Good"))
        asyncio.run(cloner.process_url("/redfish/v1/Gone"))

        assert os.path.isfile(os.path.join(out, "redfish", "v1", "Good", "index.json"))
        assert not os.path.exists(os.path.join(out, "redfish", "v1", "Gone"))
        assert cloner.visited_urls == {"/redfish/v1/Good"}
        assert cloner.skipped_urls == {"/redfish/v1/Gone"}
