# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Supermicro Chassis Drive: the BMC's ``DriveFormFactor`` is passed through.

Supermicro sends ``DriveFormFactor: "U2"`` on its NVMe backplane drives. ``U2`` is a value of
the DMTF ``FormFactor`` enumeration, so it is kept as the BMC sent it.
"""

from __future__ import annotations

from typing import Any, Dict

from ...optional import optional
from .base import BaseChassisDriveNormalizer


class SupermicroChassisDriveNormalizer(BaseChassisDriveNormalizer):
    def field_map(self) -> Dict[str, Any]:
        m = super().field_map()
        m["DriveFormFactor"] = optional("DriveFormFactor")
        return m
