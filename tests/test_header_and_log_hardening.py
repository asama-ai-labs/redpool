# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""BMC-supplied header values are printable ASCII, and the redfish logger stays quiet at DEBUG."""

from __future__ import annotations

import io
import logging
import unittest

from redpool.queue_logging import install_queue_logging
from redpool.responses import header_safe


class TestHeaderSafe(unittest.TestCase):
    def test_crlf_cannot_add_headers(self) -> None:
        out = header_safe("Dell\r\nX-Injected: 1")
        self.assertNotIn("\r", out)
        self.assertNotIn("\n", out)
        self.assertEqual(out, "DellX-Injected: 1")

    def test_non_ascii_and_control_characters_are_dropped(self) -> None:
        self.assertEqual(header_safe("Sup\x00er\x7fmicroé "), "Supermicro")

    def test_plain_values_are_unchanged(self) -> None:
        self.assertEqual(header_safe("ProLiant DL360 Gen10"), "ProLiant DL360 Gen10")


class TestPassthroughHeaders(unittest.TestCase):
    def test_bmc_headers_cannot_add_response_headers(self) -> None:
        from redpool.proxy import RedfishProxy

        class _Response:
            def getheader(self, name: str) -> str | None:
                if name == "Location":
                    return "/redfish/v1/SessionService/Sessions/1\r\nX-Injected: 1"
                if name == "ETag":
                    return "\r\n"
                return None

        headers = RedfishProxy._extract_passthrough_headers(_Response())
        self.assertEqual(
            headers["Location"], "/redfish/v1/SessionService/Sessions/1X-Injected: 1"
        )
        self.assertNotIn("\r", headers["Location"])
        self.assertNotIn("\n", headers["Location"])
        self.assertNotIn("ETag", headers)


class TestRedfishLoggerPinned(unittest.TestCase):
    def test_debug_root_level_does_not_enable_redfish_debug(self) -> None:
        root = logging.getLogger()
        saved = (root.level, list(root.handlers), logging.getLogger("redfish").level)
        try:
            listener = install_queue_logging(level=logging.DEBUG, stream=io.StringIO())
            self.assertFalse(
                logging.getLogger("redfish.rest.v1").isEnabledFor(logging.DEBUG)
            )
            listener.stop()
        finally:
            root.handlers[:] = saved[1]
            root.setLevel(saved[0])
            logging.getLogger("redfish").setLevel(saved[2])


if __name__ == "__main__":
    unittest.main()
