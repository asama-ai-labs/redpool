#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""
Generate fishymetrics golden files by running fishymetrics against the mock server
for each fixtures model and saving the Prometheus scrape output.

With proxy (default):  fixtures/<vendor>/<model>/fishymetrics_redpool.prom
Without proxy (--no-proxy): fixtures/<vendor>/<model>/fishymetrics_direct.prom

Requires: fishymetrics submodule built (make -C third_party/fishymetrics build), uv for mock/proxy.
Usage (from repo root):
  uv run python scripts/generate_fishymetrics_golden.py
  uv run python scripts/generate_fishymetrics_golden.py --no-proxy
  uv run python scripts/generate_fishymetrics_golden.py --model Dell/PowerEdge_R630
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import fishymetrics_common as fm  # noqa: E402
from third_party_paths import FISHYMETRICS_ROOT  # noqa: E402


def main():
    ap = argparse.ArgumentParser(
        description="Generate fishymetrics golden .prom files per model"
    )
    ap.add_argument(
        "--model", help="Run only this vendor/model (e.g. Dell/PowerEdge_R630)"
    )
    ap.add_argument(
        "--no-proxy",
        action="store_true",
        help="Run fishymetrics directly against mock (no redpool proxy)",
    )
    ap.add_argument("--fishy-port", type=int, default=10023)
    ap.add_argument("--mock-port", type=int, default=18888)
    ap.add_argument("--proxy-port", type=int, default=18080)
    ap.add_argument("--scrape-timeout", type=int, default=180)
    ap.add_argument("--partial-scrape", action="store_true")
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()

    if not fm.FISHY_BIN.exists() and not args.skip_build:
        print("Building fishymetrics...", flush=True)
        r = fm.run_cmd(
            ["make", "-C", str(FISHYMETRICS_ROOT), "build"],
            capture=True,
        )
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            sys.exit(1)
    if not fm.FISHY_BIN.exists():
        print(
            f"fishymetrics binary not found at {fm.FISHY_BIN}; run make -C third_party/fishymetrics build",
            file=sys.stderr,
        )
        sys.exit(1)

    models = list(fm.get_models())
    if args.model:
        want = args.model.split("/")
        if len(want) == 2:
            models = [(v, m) for v, m in models if (v, m) == (want[0], want[1])]
        else:
            models = [(v, m) for v, m in models if v == want[0]]
        if not models:
            print(f"No model matching {args.model}", file=sys.stderr)
            sys.exit(1)

    mode = "direct" if args.no_proxy else "redpool"
    suffix = f"fishymetrics_{mode}.prom"
    n_models = len(models)
    print(f"Generating {suffix} for {n_models} model(s)...", flush=True)
    failed = 0
    for idx, (vendor, model) in enumerate(models, 1):
        key = f"{vendor}/{model}"
        print(f"[{idx}/{n_models}] {key}", flush=True)
        if args.no_proxy:
            metrics_text, err = fm.run_one_model_metrics_direct(
                vendor,
                model,
                mock_port=args.mock_port,
                fishy_port=args.fishy_port,
                scrape_timeout=args.scrape_timeout,
            )
        else:
            metrics_text, err = fm.run_one_model_metrics(
                vendor,
                model,
                mock_port=args.mock_port,
                proxy_port=args.proxy_port,
                fishy_port=args.fishy_port,
                scrape_timeout=args.scrape_timeout,
                partial_scrape=args.partial_scrape,
            )
        if err:
            print(f"  Error: {err}", file=sys.stderr)
            failed += 1
            continue
        out_path = fm.FIXTURES / vendor / model / suffix
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(metrics_text or "", encoding="utf-8")
        print(f"  Wrote {out_path}", flush=True)
    print(f"Done. {n_models - failed} written, {failed} failed.", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
