# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Lenovo chassis PCIeDevice normalizer."""

from __future__ import annotations

from typing import Any, Dict

from ...types import NormalizationContext
from .base import BasePCIeDeviceNormalizer


def _lenovo_pcie_device_links(ctx: NormalizationContext) -> Dict[str, Any]:
    """Copy ``Links`` and drop XCC's malformed deprecation annotation.

    XCC puts ``Links/PCIeFunctions@Redfish.Deprecated`` inside ``Links``. The
    slash fails the Redfish annotation pattern. ``PCIeFunctions`` itself stays.
    """
    links = ctx.data.get("Links")
    if not isinstance(links, dict):
        return {}
    links = dict(links)
    links.pop("Links/PCIeFunctions@Redfish.Deprecated", None)
    return links


class LenovoChassisPCIeDeviceNormalizer(BasePCIeDeviceNormalizer):
    def field_map(self) -> Dict[str, Any]:
        mapping = super().field_map()
        mapping["Links"] = _lenovo_pcie_device_links
        return mapping
