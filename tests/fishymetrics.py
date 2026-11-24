# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""
Test that fishymetrics run against the mock server (through the redpool proxy) produces
Prometheus metrics that match the golden file for each model.

Golden files live at fixtures/<vendor>/<model>/fishymetrics_redpool.prom (through proxy)
and fishymetrics_direct.prom (direct to mock). Generate them with:
  uv run python scripts/generate_fishymetrics_golden.py
  uv run python scripts/generate_fishymetrics_golden.py --no-proxy

Requires: fishymetrics submodule built (make -C third_party/fishymetrics build), uv for mock/proxy.
Run from repo root: uv run python -m unittest tests.fishymetrics
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import fishymetrics_common as fm  # noqa: E402


def get_models_with_golden(suffix: str = "_redpool"):
    """Yield (vendor, model) for each fixtures model that has fishymetrics{suffix}.prom."""
    fname = f"fishymetrics{suffix}.prom"
    for vendor in sorted(fm.FIXTURES.iterdir()):
        if not vendor.is_dir():
            continue
        for model in sorted(vendor.iterdir()):
            if not model.is_dir():
                continue
            if (model / fname).is_file():
                yield vendor.name, model.name


@unittest.skipUnless(
    fm.FISHY_BIN.exists(),
    "fishymetrics binary not found; run make -C third_party/fishymetrics build",
)
class TestFishymetricsGolden(unittest.TestCase):
    """Compare live fishymetrics /metrics output to golden files per model."""

    def test_fishymetrics_metrics_match_golden(self):
        models = list(get_models_with_golden("_redpool"))
        if not models:
            self.skipTest(
                "No fishymetrics_redpool.prom golden files; run scripts/generate_fishymetrics_golden.py"
            )
        for vendor, model in models:
            key = f"{vendor}/{model}"
            with self.subTest(model=key):
                golden_path = fm.FIXTURES / vendor / model / "fishymetrics_redpool.prom"
                golden_normalized = fm.normalize_prom_metrics(
                    golden_path.read_text(encoding="utf-8")
                )
                metrics_text, err = fm.run_one_model_metrics(
                    vendor,
                    model,
                    mock_port=18888,
                    proxy_port=18080,
                    fishy_port=10023,
                    scrape_timeout=180,
                    partial_scrape=False,
                )
                if err:
                    self.fail(f"{key}: {err}")
                actual_normalized = fm.normalize_prom_metrics(metrics_text or "")
                self.assertEqual(
                    actual_normalized,
                    golden_normalized,
                    f"{key}: metrics differ from golden file",
                )

    def test_fishymetrics_direct_metrics_match_golden(self):
        models = list(get_models_with_golden("_direct"))
        if not models:
            self.skipTest(
                "No fishymetrics_direct.prom golden files; run scripts/generate_fishymetrics_golden.py --no-proxy"
            )
        for vendor, model in models:
            key = f"{vendor}/{model}"
            with self.subTest(model=key):
                golden_path = fm.FIXTURES / vendor / model / "fishymetrics_direct.prom"
                golden_normalized = fm.normalize_prom_metrics(
                    golden_path.read_text(encoding="utf-8")
                )
                metrics_text, err = fm.run_one_model_metrics_direct(
                    vendor,
                    model,
                    mock_port=18889,
                    fishy_port=10024,
                    scrape_timeout=180,
                )
                if err:
                    self.fail(f"{key}: {err}")
                actual_normalized = fm.normalize_prom_metrics(metrics_text or "")
                self.assertEqual(
                    actual_normalized,
                    golden_normalized,
                    f"{key}: metrics differ from golden file",
                )
