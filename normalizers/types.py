# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Protocol

if TYPE_CHECKING:
    from redpool.config import RedpoolConfig


class RedfishGetResponse(Protocol):
    """Minimal response shape used by ``redfish_get_json`` after ``client.get``."""

    status: int
    dict: Dict[str, Any]


class PrefetchRedfishClient(Protocol):
    """Redfish client surface used from normalizer ``prefetch`` (via ``redfish_get_json``)."""

    def get(
        self,
        path: str,
        args: Any = None,
        headers: Any = None,
    ) -> RedfishGetResponse: ...


class PrefetchLogger(Protocol):
    """Logging surface used from normalizer ``prefetch`` today (errors only)."""

    def error(self, msg: object, *args: object, **kwargs: object) -> None: ...


@dataclass
class NormalizationContext:
    """Typed context passed to normalizer lambdas and prefetch methods.

    Attributes:
        data: Raw Redfish response dict.
        client: Redfish HTTP client for additional API calls (prefetch only);
            ``None`` when callers only exercise field maps (tests).
        logger: Logger used for prefetch diagnostics (``error`` is used today).
        prefetched: Data gathered during the prefetch phase, available to
                    field-map lambdas as a read-only cache.
        config: Redpool configuration (normalization feature flags, etc.).
        vendor: Vendor string from server metadata (e.g. for serial masking).
        model: Model string from server metadata (e.g. for serial masking).
        resource_path: Client Redfish path for this response, when the proxy has one.
    """

    data: Dict[str, Any]
    client: PrefetchRedfishClient | None
    logger: PrefetchLogger
    prefetched: Dict[str, Any] = field(default_factory=dict)
    config: RedpoolConfig | None = None
    vendor: str = ""
    model: str = "unknown"
    resource_path: str = ""

    @property
    def odata_type(self) -> str:
        return self.data.get("@odata.type", "")

    @property
    def odata_id(self) -> str:
        return self.data.get("@odata.id", "")
