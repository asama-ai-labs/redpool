# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Response bodies the proxy returns to clients.

Kept free of side effects so both the proxy core and the mitmproxy addon (which
starts a metrics server on import) can use it, and so it can be tested directly.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Tuple

# DMTF Base message registry, pinned by third_party/Redfish-Publications
# (registries/Base.1.24.0.json defines GeneralError).
GENERAL_ERROR_MESSAGE_ID = "Base.1.24.0.GeneralError"
MESSAGE_SCHEMA = "#Message.v1_4_0.Message"


@dataclass(frozen=True)
class RawBody:
    """An upstream body that is not a JSON object or array, passed through unchanged.

    Used for XML (``$metadata``), HTML error pages, and empty bodies (204), so the
    client receives exactly what the BMC sent, with its Content-Type.
    """

    content: bytes
    content_type: str


_DEFAULT_RESOLUTION = (
    "Retry the request. If the problem persists, check the "
    "connection between the proxy and the BMC."
)


def redfish_error_body(message: str, resolution: str = _DEFAULT_RESOLUTION) -> dict:
    """A DMTF-style error object, for responses the proxy synthesizes itself.

    Used only when there is no upstream response at all. Upstream error bodies
    are passed through as the BMC sent them.
    """
    return {
        "error": {
            "code": GENERAL_ERROR_MESSAGE_ID,
            "message": message,
            "@Message.ExtendedInfo": [
                {
                    "@odata.type": MESSAGE_SCHEMA,
                    "MessageId": GENERAL_ERROR_MESSAGE_ID,
                    "Message": message,
                    "Severity": "Critical",
                    "Resolution": resolution,
                }
            ],
        }
    }


def encode_body(body: Any) -> Tuple[bytes, Optional[str]]:
    """Serialize a body for the client.

    Returns the bytes and the Content-Type to use, or ``None`` for the default
    ``application/json``.
    """
    if isinstance(body, RawBody):
        return body.content, body.content_type
    if isinstance(body, (dict, list)):
        return json.dumps(body).encode("utf-8"), None
    if isinstance(body, str):
        return body.encode("utf-8"), None
    if isinstance(body, bytes):
        return body, None
    raise TypeError(f"Cannot encode response body of type {type(body).__name__}")


_NON_PRINTABLE_ASCII = re.compile(r"[^\x20-\x7e]")


def header_safe(value: object) -> str:
    """Printable ASCII only, so a BMC-supplied value cannot add or split response headers."""
    return _NON_PRINTABLE_ASCII.sub("", str(value))
