# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""BMC responses reach the client as the BMC sent them: status, body and headers."""

import asyncio
import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

from redpool.mitm_proxy import request as mitm_request
from redpool.proxy import RedfishProxy, ServerMetadata
from redpool.responses import (
    GENERAL_ERROR_MESSAGE_ID,
    RawBody,
    encode_body,
    redfish_error_body,
)

SETTINGS = "/redfish/v1/Systems/1/Bios/Settings"
EXTENDED_ERROR = {
    "error": {
        "code": "Base.1.24.0.PropertyValueNotInList",
        "message": "The value Bogus is not in the list of acceptable values.",
        "@Message.ExtendedInfo": [
            {
                "@odata.type": "#Message.v1_4_0.Message",
                "MessageId": "Base.1.24.0.PropertyValueNotInList",
                "Message": "The value Bogus is not in the list of acceptable values.",
                "Severity": "Warning",
            }
        ],
    }
}


class FakeRest:
    """A RestResponse stand-in: status, decoded text and headers."""

    def __init__(self, status, text="", headers=None):
        self.status = status
        self.text = text
        self._headers = {k.lower(): v for k, v in (headers or {}).items()}

    def getheader(self, name):
        return self._headers.get(name.lower())


class ErrorPassthroughTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proxy = RedfishProxy()
        self.client = MagicMock()

    def test_upstream_error_body_and_status_are_returned(self) -> None:
        text = json.dumps(EXTENDED_ERROR)
        self.client.patch.return_value = FakeRest(
            400, text, {"Content-Type": "application/json"}
        )
        body, status, _ = self.proxy._fetch_upstream(
            self.client, SETTINGS, "PATCH", {"a": 1}
        )
        self.assertEqual(status, 400)
        self.assertEqual(body, EXTENDED_ERROR)
        self.assertEqual(
            body["error"]["@Message.ExtendedInfo"][0]["MessageId"],
            "Base.1.24.0.PropertyValueNotInList",
        )

    def test_non_json_body_passes_through_raw(self) -> None:
        self.client.get.return_value = FakeRest(
            200, "<edmx:Edmx/>", {"Content-Type": "application/xml"}
        )
        body, status, _ = self.proxy._fetch_upstream(
            self.client, "/redfish/v1/$metadata", "GET", None
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(body, RawBody)
        self.assertEqual(body.content, b"<edmx:Edmx/>")
        self.assertEqual(body.content_type, "application/xml")

    def test_html_error_page_passes_through_with_its_status(self) -> None:
        self.client.get.return_value = FakeRest(
            503, "<html>Service Unavailable</html>", {"Content-Type": "text/html"}
        )
        body, status, _ = self.proxy._fetch_upstream(
            self.client, "/redfish/v1/Chassis", "GET", None
        )
        self.assertEqual(status, 503)
        self.assertEqual(body.content, b"<html>Service Unavailable</html>")
        self.assertEqual(body.content_type, "text/html")

    def test_empty_no_content_response_keeps_its_status(self) -> None:
        self.client.delete.return_value = FakeRest(204, "")
        body, status, _ = self.proxy._fetch_upstream(
            self.client, SETTINGS, "DELETE", None
        )
        self.assertEqual(status, 204)
        self.assertEqual(
            body, RawBody(content=b"", content_type="application/octet-stream")
        )

    def test_precondition_failed_keeps_etag(self) -> None:
        self.client.patch.return_value = FakeRest(
            412,
            json.dumps(EXTENDED_ERROR),
            {"Content-Type": "application/json", "ETag": 'W/"abc"'},
        )
        _, status, headers = self.proxy._fetch_upstream(
            self.client, SETTINGS, "PATCH", {"a": 1}
        )
        self.assertEqual(status, 412)
        self.assertEqual(headers.get("ETag"), 'W/"abc"')

    def test_rate_limit_keeps_retry_after(self) -> None:
        self.client.get.return_value = FakeRest(
            429, json.dumps(EXTENDED_ERROR), {"Retry-After": "30"}
        )
        _, status, headers = self.proxy._fetch_upstream(
            self.client, "/redfish/v1/Chassis", "GET", None
        )
        self.assertEqual(status, 429)
        self.assertEqual(headers.get("Retry-After"), "30")

    def test_no_upstream_response_returns_nothing(self) -> None:
        self.client.get.return_value = None
        body, status, headers = self.proxy._fetch_upstream(
            self.client, "/redfish/v1/Chassis", "GET", None
        )
        self.assertIsNone(body)
        self.assertEqual(headers, {})

    def test_query_string_is_forwarded_to_the_bmc(self) -> None:
        path = "/redfish/v1/Systems?$top=1&$expand=*($levels=1)"
        self.client.get.return_value = FakeRest(200, json.dumps({"Members": []}))
        self.proxy._fetch_upstream(self.client, path, "GET", None)
        self.client.get.assert_called_once_with(path)

    def test_query_request_is_normalized(self) -> None:
        meta = ServerMetadata(hostname="bmc", vendor="Dell", model="PowerEdge R630")
        body = {"Members": [{"@odata.id": "/redfish/v1/Systems/1"}]}
        result, returned_meta, status, norm = self.proxy._build_proxy_response(
            body,
            200,
            "/redfish/v1/Systems?$top=1",
            meta,
            self.client,
            "bmc",
            "Dell",
            "PowerEdge R630",
            "GET",
            0.0,
        )
        self.assertEqual(status, 200)
        self.assertEqual(norm, "normalized")

    def test_raw_body_is_passed_through_without_normalization(self) -> None:
        meta = ServerMetadata(hostname="bmc", vendor="Dell", model="PowerEdge R630")
        raw = RawBody(content=b"<feed/>", content_type="application/xml")
        result, _, status, norm = self.proxy._build_proxy_response(
            raw,
            200,
            "/redfish/v1/Systems",
            meta,
            self.client,
            "bmc",
            "Dell",
            "PowerEdge R630",
            "GET",
            0.0,
        )
        self.assertIs(result, raw)
        self.assertEqual(status, 200)
        self.assertEqual(norm, "passthrough")


class MitmResponseTests(unittest.TestCase):
    """The mitmproxy addon sends what the proxy core returns."""

    def _flow(self, url: str, method: str = "PATCH"):
        flow = MagicMock()
        flow.request.pretty_url = url
        flow.request.path = urlparse(url).path
        flow.request.method = method
        flow.request.headers = {"Authorization": "Basic dXNlcjpwYXNz"}
        flow.request.content = b"{}"
        flow.response = None
        return flow

    def _run(self, flow, proxy, upstream):
        with (
            patch("redpool.mitm_proxy.redfish_proxy", proxy),
            patch.object(proxy, "proxy_request", return_value=upstream) as call,
        ):
            asyncio.run(mitm_request(flow))
        return call

    def test_upstream_error_status_headers_and_body_reach_the_client(self) -> None:
        proxy = RedfishProxy()
        upstream = (
            EXTENDED_ERROR,
            None,
            412,
            "passthrough",
            {"ETag": 'W/"abc"'},
        )
        flow = self._flow(
            "https://bmc.example.invalid/redfish/v1/Systems/1/Bios/Settings"
        )
        self._run(flow, proxy, upstream)
        self.assertEqual(flow.response.status_code, 412)
        self.assertEqual(flow.response.headers.get("ETag"), 'W/"abc"')
        self.assertEqual(json.loads(flow.response.content), EXTENDED_ERROR)

    def test_non_json_upstream_body_keeps_its_content_type(self) -> None:
        proxy = RedfishProxy()
        raw = RawBody(content=b"<edmx:Edmx/>", content_type="application/xml")
        flow = self._flow("https://bmc.example.invalid/redfish/v1/$metadata", "GET")
        self._run(flow, proxy, (raw, None, 200, "passthrough", {}))
        self.assertEqual(flow.response.status_code, 200)
        self.assertEqual(flow.response.content, b"<edmx:Edmx/>")
        self.assertEqual(flow.response.headers.get("Content-Type"), "application/xml")

    def test_query_string_reaches_the_proxy(self) -> None:
        proxy = RedfishProxy()
        flow = self._flow(
            "https://bmc.example.invalid/redfish/v1/Systems?$top=1&$select=Name", "GET"
        )
        call = self._run(flow, proxy, ({"Members": []}, None, 200, "passthrough", {}))
        self.assertEqual(
            call.call_args.kwargs["path"], "/redfish/v1/Systems?$top=1&$select=Name"
        )

    def test_no_upstream_response_gets_a_dmtf_error_object(self) -> None:
        proxy = RedfishProxy()
        flow = self._flow("https://bmc.example.invalid/redfish/v1/Systems/1", "GET")
        self._run(flow, proxy, (None, None, 500, "error", {}))
        self.assertEqual(flow.response.status_code, 500)
        self.assertEqual(flow.response.headers.get("Content-Type"), "application/json")
        body = json.loads(flow.response.content)
        self.assertEqual(body["error"]["code"], GENERAL_ERROR_MESSAGE_ID)
        self.assertEqual(flow.response.headers.get("X-Redpool-Status"), "error")


class ResponseHelperTests(unittest.TestCase):
    def test_redfish_error_body_is_a_dmtf_error_object(self) -> None:
        body = redfish_error_body("no response")
        self.assertEqual(body["error"]["code"], GENERAL_ERROR_MESSAGE_ID)
        info = body["error"]["@Message.ExtendedInfo"][0]
        self.assertEqual(info["MessageId"], GENERAL_ERROR_MESSAGE_ID)
        self.assertEqual(info["Message"], "no response")
        self.assertEqual(info["Severity"], "Critical")

    def test_encode_body_json_objects_and_lists(self) -> None:
        self.assertEqual(encode_body({"a": 1}), (b'{"a": 1}', None))
        self.assertEqual(encode_body([1, 2]), (b"[1, 2]", None))

    def test_encode_body_raw_keeps_bytes_and_type(self) -> None:
        self.assertEqual(
            encode_body(RawBody(content=b"<x/>", content_type="application/xml")),
            (b"<x/>", "application/xml"),
        )

    def test_encode_body_rejects_unknown_types(self) -> None:
        with self.assertRaises(TypeError):
            encode_body(42)


if __name__ == "__main__":
    unittest.main()
