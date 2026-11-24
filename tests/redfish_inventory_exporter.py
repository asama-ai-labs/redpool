# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""
Test that redfish-inventory-exporter run against the mock server (through the redpool proxy or direct)
produces Prometheus metrics that match the golden file for each model.

Golden files live at fixtures/<vendor>/<model>/redfish_inventory_exporter_redpool.prom (through proxy)
and redfish_inventory_exporter_direct.prom (direct to mock). Generate them with:
  uv run python scripts/generate_redfish_inventory_exporter_golden.py
  uv run python scripts/generate_redfish_inventory_exporter_golden.py --no-proxy

Requires: redfish-inventory-exporter submodule built, uv for mock/proxy.
Run from repo root: uv run python -m unittest tests.redfish_inventory_exporter
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import redfish_inventory_exporter_common as frc  # noqa: E402


def get_models_with_golden(suffix: str = "_redpool"):
    """Yield (vendor, model) for each fixtures model that has redfish_inventory_exporter{suffix}.prom."""
    fname = f"redfish_inventory_exporter{suffix}.prom"
    for vendor in sorted(frc.FIXTURES.iterdir()):
        if not vendor.is_dir():
            continue
        for model in sorted(vendor.iterdir()):
            if not model.is_dir():
                continue
            if (model / fname).is_file():
                yield vendor.name, model.name


@unittest.skipUnless(
    frc.EXPORTER_BIN.exists(),
    "redfish-inventory-exporter binary not found; run go build in third_party/redfish-inventory-exporter",
)
class TestRedfishInventoryExporterGolden(unittest.TestCase):
    """Compare live redfish-inventory-exporter /redfish output to golden files per model."""

    def test_redfish_inventory_exporter_metrics_match_golden(self):
        models = list(get_models_with_golden("_redpool"))
        if not models:
            self.skipTest(
                "No redfish_inventory_exporter_redpool.prom golden files; "
                "run scripts/generate_redfish_inventory_exporter_golden.py"
            )
        for vendor, model in models:
            key = f"{vendor}/{model}"
            with self.subTest(model=key):
                golden_path = (
                    frc.FIXTURES
                    / vendor
                    / model
                    / "redfish_inventory_exporter_redpool.prom"
                )
                golden_normalized = frc.normalize_prom_metrics(
                    golden_path.read_text(encoding="utf-8")
                )
                metrics_text, err = frc.run_one_model_metrics(
                    vendor,
                    model,
                    proxy_port=0,
                    scrape_timeout=180,
                    expose_prometheus_metadata=True,
                )
                if err:
                    self.fail(f"{key}: {err}")
                actual_normalized = frc.normalize_prom_metrics(metrics_text or "")
                self.assertEqual(
                    actual_normalized,
                    golden_normalized,
                    f"{key}: metrics differ from golden file",
                )

    def test_redfish_inventory_exporter_direct_metrics_match_golden(self):
        models = list(get_models_with_golden("_direct"))
        if not models:
            self.skipTest(
                "No redfish_inventory_exporter_direct.prom golden files; "
                "run scripts/generate_redfish_inventory_exporter_golden.py --no-proxy"
            )
        for vendor, model in models:
            key = f"{vendor}/{model}"
            with self.subTest(model=key):
                golden_path = (
                    frc.FIXTURES
                    / vendor
                    / model
                    / "redfish_inventory_exporter_direct.prom"
                )
                golden_normalized = frc.normalize_prom_metrics(
                    golden_path.read_text(encoding="utf-8")
                )
                metrics_text, err = frc.run_one_model_metrics_direct(
                    vendor,
                    model,
                    scrape_timeout=180,
                )
                if err:
                    self.fail(f"{key}: {err}")
                actual_normalized = frc.normalize_prom_metrics(metrics_text or "")
                self.assertEqual(
                    actual_normalized,
                    golden_normalized,
                    f"{key}: metrics differ from golden file",
                )
