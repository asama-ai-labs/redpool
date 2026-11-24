# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base Memory EnvironmentMetrics normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ....base import ResourceNormalizer
from ....optional import optional


class BaseMemoryEnvironmentMetricsNormalizer(ResourceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#EnvironmentMetrics.EnvironmentMetrics",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#EnvironmentMetrics.v1_3_0.EnvironmentMetrics",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: ctx.data.get("Name"),
        }
