# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base PCIeFunction normalizer."""

from __future__ import annotations

import re
from typing import Any, Dict

from ...base import ResourceNormalizer
from ...optional import omit_if_null, optional
from ...pci_class_code import format_pci_id, normalize_pci_class_code
from ...pcie_display import (
    pcie_function_display_name,
    prefetch_parent_pcie_device_for_function,
)
from ...types import NormalizationContext

_BDF_SUFFIX_RE = re.compile(
    r"^(.*?)(?:\s+[0-9a-fA-F]{1,2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})$"
)


def normalize_name(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    m = _BDF_SUFFIX_RE.match(value.strip())
    if m:
        return m.group(1).rstrip()
    return value


class BasePCIeFunctionNormalizer(ResourceNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_parent_pcie_device_for_function(ctx)

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#PCIeFunction.PCIeFunction",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": lambda ctx: ctx.odata_id,
            "@odata.type": "#PCIeFunction.v1_5_0.PCIeFunction",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: pcie_function_display_name(ctx, normalize_name),
            "Description": optional("Description"),
            "DeviceClass": optional("DeviceClass"),
            "FunctionType": optional("FunctionType"),
            "FunctionId": optional("FunctionId"),
            "ClassCode": omit_if_null(
                lambda ctx: normalize_pci_class_code(ctx.data.get("ClassCode"))
            ),
            "DeviceId": omit_if_null(
                lambda ctx: format_pci_id(ctx.data.get("DeviceId"), 2)
            ),
            "VendorId": omit_if_null(
                lambda ctx: format_pci_id(ctx.data.get("VendorId"), 2)
            ),
            "SubsystemId": omit_if_null(
                lambda ctx: format_pci_id(ctx.data.get("SubsystemId"), 2)
            ),
            "SubsystemVendorId": omit_if_null(
                lambda ctx: format_pci_id(ctx.data.get("SubsystemVendorId"), 2)
            ),
            "RevisionId": omit_if_null(
                lambda ctx: format_pci_id(ctx.data.get("RevisionId"), 1)
            ),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#PCIeFunctionCollection.PCIeFunctionCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": lambda ctx: ctx.odata_id,
    "@odata.type": "#PCIeFunctionCollection.PCIeFunctionCollection",
    "Members": optional("Members"),
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of PCIe Functions",
    "Name": "PCIeFunctionCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
