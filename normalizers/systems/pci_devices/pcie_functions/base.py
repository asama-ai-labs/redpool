# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Base PCIeFunction normalizer for functions under Systems/PCIeDevices.

For standard Redfish data this passes through fields unchanged.  For HPE
servers (which lack real PCIeFunction sub-resources) the
``generate_normalized_outputs.py`` script creates synthetic function JSON
from the parent ``HpeServerPciDevice`` data; this normalizer handles both.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from ....base import ResourceNormalizer
from ....optional import omit_if_null, optional
from ....pci_class_code import format_pci_id, normalize_pci_class_code
from ....pcie_display import (
    pcie_function_display_name,
    prefetch_parent_pcie_device_for_function,
)
from ....types import NormalizationContext
from ....url_rewrites import rewrite_odata_id

_BDF_SUFFIX_RE = re.compile(
    r"^(.*?)(?:\s+[0-9a-fA-F]{1,2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})$"
)


def _normalize_odata_id(ctx):
    return rewrite_odata_id(ctx.odata_id)


def _normalize_name(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    m = _BDF_SUFFIX_RE.match(value.strip())
    if m:
        return m.group(1).rstrip()
    return value


class BaseSystemsPCIeFunctionNormalizer(ResourceNormalizer):
    def prefetch(self, ctx: NormalizationContext) -> None:
        prefetch_parent_pcie_device_for_function(ctx)

    def field_map(self) -> Dict[str, Any]:
        return {
            "@odata.context": "/redfish/v1/$metadata#PCIeFunction.PCIeFunction",
            "@odata.etag": optional("@odata.etag"),
            "@odata.id": _normalize_odata_id,
            "@odata.type": "#PCIeFunction.v1_5_0.PCIeFunction",
            "Id": lambda ctx: ctx.data.get("Id"),
            "Name": lambda ctx: pcie_function_display_name(ctx, _normalize_name),
            "Description": optional("Description"),
            "DeviceClass": optional("DeviceClass"),
            "FunctionType": optional("FunctionType"),
            "FunctionId": omit_if_null(
                lambda ctx: (
                    ctx.data.get("FunctionId")
                    if ctx.data.get("FunctionId") is not None
                    else ctx.data.get("FunctionID")
                )
            ),
            "ClassCode": omit_if_null(
                lambda ctx: normalize_pci_class_code(ctx.data.get("ClassCode"))
            ),
            "DeviceId": omit_if_null(
                lambda ctx: format_pci_id(
                    ctx.data.get("DeviceId") or ctx.data.get("DeviceID"), 2
                )
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
                lambda ctx: format_pci_id(
                    ctx.data.get("RevisionId") or ctx.data.get("RevisionID"), 1
                )
            ),
            "Status": lambda ctx: ctx.data.get("Status", {}),
            "Links": lambda ctx: ctx.data.get("Links", {}),
            "Oem": lambda ctx: ctx.data.get("Oem", {}),
        }


def _collection_members(ctx: NormalizationContext) -> list[Dict[str, str]] | None:
    members = ctx.data.get("Members")
    if members is None:
        return None
    return [{"@odata.id": rewrite_odata_id(m.get("@odata.id", ""))} for m in members]


COLLECTION_MAPPING: Dict[str, Any] = {
    "@odata.context": "/redfish/v1/$metadata#PCIeFunctionCollection.PCIeFunctionCollection",
    "@odata.etag": optional("@odata.etag"),
    "@odata.id": _normalize_odata_id,
    "@odata.type": "#PCIeFunctionCollection.PCIeFunctionCollection",
    "Members": _collection_members,
    "Members@odata.count": optional("Members@odata.count"),
    "Description": "Collection of PCIe Functions",
    "Name": "PCIeFunctionCollection",
    "Oem": lambda ctx: ctx.data.get("Oem", {}),
}
