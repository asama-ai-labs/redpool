# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""URL path segment rewrites for vendor-specific Redfish paths.

HPE uses non-standard ``PCIDevices`` (OEM HpeServerPciDevice collection)
instead of the Redfish-standard ``PCIeDevices``.  The normalizers register
under the vendor path (``Systems/PCIDevices``) but produce canonical
``PCIeDevices`` URLs in their output.

URL rewrite behaviour:
- Client requests canonical path (e.g. GET /redfish/v1/Systems/1/PCIeDevices).
  Proxy tries that; on 404 it tries the vendor path (reverse rewrite), e.g.
  GET /redfish/v1/Systems/1/PCIDevices, and returns normalized response.
- Path segment rewrites apply to both collection and member paths:
  /PCIeDevices/4 -> /PCIDevices/4, and vice versa via rewrite_odata_id /
  reverse_rewrite_path.
- Single-resource paths are covered: .../PCIDevices/7 and .../PCIeDevices/7
  are the same segment rewrite (plural form only; Redfish uses plural).

The mappings here are used by:
* ``generate_normalized_outputs.py`` — rewrite output file paths
* ``tests/redpool.py`` ``MockRedfishClient`` — reverse-rewrite when
  resolving original files from normalized paths
* ``redpool/proxy.py`` — rewrite client-facing URLs to upstream BMC paths
"""

from __future__ import annotations

# original_segment → canonical_segment
SEGMENT_REWRITES: dict[str, str] = {
    "PCIDevices": "PCIeDevices",
}

# canonical_segment → original_segment (reverse lookup)
REVERSE_SEGMENT_REWRITES: dict[str, str] = {v: k for k, v in SEGMENT_REWRITES.items()}


def rewrite_path(path: str) -> str:
    """Apply segment rewrites to a file-system or URL path (original → canonical)."""
    for old, new in SEGMENT_REWRITES.items():
        path = path.replace(f"/{old}/", f"/{new}/")
        path = path.replace(f"/{old}.", f"/{new}.")
        if path.endswith(f"/{old}"):
            path = path[: -len(old)] + new
    return path


def reverse_rewrite_path(path: str) -> str:
    """Reverse segment rewrites (canonical → original)."""
    for canon, orig in REVERSE_SEGMENT_REWRITES.items():
        path = path.replace(f"/{canon}/", f"/{orig}/")
        path = path.replace(f"/{canon}.", f"/{orig}.")
        if path.endswith(f"/{canon}"):
            path = path[: -len(canon)] + orig
    return path


def rewrite_odata_id(odata_id: str) -> str:
    """Rewrite @odata.id URL segments (original → canonical)."""
    for old, new in SEGMENT_REWRITES.items():
        odata_id = odata_id.replace(f"/{old}/", f"/{new}/")
        if odata_id.endswith(f"/{old}"):
            odata_id = odata_id[: -len(old)] + new
    return odata_id
