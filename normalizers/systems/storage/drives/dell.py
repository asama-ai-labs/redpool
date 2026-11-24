# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Dell Drive normalization for Systems/Storage/Drives (shared with Chassis/Drives)."""

from __future__ import annotations

from typing import Any, Dict

from ....chassis.drives.dell import dell_drive_field_map
from .base import BaseStorageDriveNormalizer


class DellStorageDriveNormalizer(BaseStorageDriveNormalizer):
    def field_map(self) -> Dict[str, Any]:
        return dell_drive_field_map(super().field_map())
