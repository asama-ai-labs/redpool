#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""
Generate redfish-inventory-exporter golden files by running redfish-inventory-exporter against the mock
server for each fixtures model and saving the Prometheus scrape output.

With proxy (default):  fixtures/<vendor>/<model>/redfish_inventory_exporter_redpool.prom
Without proxy (--no-proxy): fixtures/<vendor>/<model>/redfish_inventory_exporter_direct.prom

Requires: redfish-inventory-exporter submodule built under third_party/
          (go build -o build/redfish-inventory-exporter . in third_party/redfish-inventory-exporter),
          uv for mock/proxy.
Usage (from repo root):
  uv run python scripts/generate_redfish_inventory_exporter_golden.py
  uv run python scripts/generate_redfish_inventory_exporter_golden.py --no-proxy
  uv run python scripts/generate_redfish_inventory_exporter_golden.py --model Dell/PowerEdge_R630
  uv run python scripts/generate_redfish_inventory_exporter_golden.py --jobs 1

Golden generation always uses a single mitmdump + mitm_proxy per model (non-sharded redpool),
not redpool-shard-proxy. Models run in parallel by default (--jobs 4).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import redfish_inventory_exporter_common as frc  # noqa: E402
from third_party_paths import REDFISH_INVENTORY_EXPORTER_ROOT  # noqa: E402


def _run_one_model(
    vendor: str,
    model: str,
    *,
    no_proxy: bool,
    mock_port: int,
    proxy_port: int,
    scrape_timeout: int,
    disable_collectors: str | None,
    suffix: str,
) -> tuple[str, Path | None, str | None]:
    """Return (key, out_path_or_None, error_or_None)."""
    key = f"{vendor}/{model}"
    if no_proxy:
        metrics_text, err = frc.run_one_model_metrics_direct(
            vendor,
            model,
            mock_port=mock_port,
            scrape_timeout=scrape_timeout,
            disable_collectors=disable_collectors,
        )
    else:
        metrics_text, err = frc.run_one_model_metrics(
            vendor,
            model,
            mock_port=mock_port,
            proxy_port=proxy_port,
            scrape_timeout=scrape_timeout,
            disable_collectors=disable_collectors,
            shard_workers=None,
            expose_prometheus_metadata=True,
        )
    if err:
        return key, None, err
    out_path = frc.FIXTURES / vendor / model / suffix
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        frc.normalize_prom_metrics(metrics_text or ""), encoding="utf-8"
    )
    return key, out_path, None


def main():
    ap = argparse.ArgumentParser(
        description="Generate redfish-inventory-exporter golden .prom files per model"
    )
    ap.add_argument(
        "--model", help="Run only this vendor/model (e.g. Dell/PowerEdge_R630)"
    )
    ap.add_argument(
        "--no-proxy",
        action="store_true",
        help="Run redfish-inventory-exporter directly against mock (no redpool proxy)",
    )
    ap.add_argument(
        "--mock-port",
        type=int,
        default=0,
        help="Mock listen port; 0 (default) picks a free port",
    )
    ap.add_argument(
        "--proxy-port",
        type=int,
        default=0,
        help="MITM listen port; 0 (default) picks a free port",
    )
    ap.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=4,
        help="Parallel model workers (default: 4). Use 1 for serial.",
    )
    ap.add_argument(
        "--scrape-timeout",
        type=int,
        default=120,
        help="Curl max-time for scrape (seconds). Direct (--no-proxy) is fast; redpool path may need 300+ for log-heavy mocks.",
    )
    ap.add_argument(
        "--disable-collectors",
        default="",
        help="Comma-separated collector names to disable when running redfish-inventory-exporter (e.g. logs,pcie).",
    )
    ap.add_argument("--skip-build", action="store_true")
    args = ap.parse_args()

    if args.jobs < 1:
        print("--jobs must be >= 1", file=sys.stderr)
        sys.exit(1)
    if args.jobs > 1 and (args.mock_port > 0 or args.proxy_port > 0):
        print(
            "Fixed --mock-port/--proxy-port cannot be used with --jobs > 1 "
            "(port collisions); use --jobs 1 or leave ports at 0.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not args.skip_build:
        print("Building redfish-inventory-exporter...", flush=True)
        (REDFISH_INVENTORY_EXPORTER_ROOT / "build").mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["go", "build", "-o", str(frc.EXPORTER_BIN), "."],
            cwd=str(REDFISH_INVENTORY_EXPORTER_ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            sys.exit(1)
    if not frc.EXPORTER_BIN.exists():
        print(
            f"redfish-inventory-exporter not found at {frc.EXPORTER_BIN}; run go build -o build/redfish-inventory-exporter . in third_party/redfish-inventory-exporter",
            file=sys.stderr,
        )
        sys.exit(1)

    models = list(frc.get_models())
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
    suffix = f"redfish_inventory_exporter_{mode}.prom"
    n_models = len(models)
    workers = min(args.jobs, n_models)
    print(
        f"Generating {suffix} for {n_models} model(s) with {workers} job(s)...",
        flush=True,
    )

    disable_collectors = args.disable_collectors or None
    failed = 0
    done = 0

    def _submit_args(vendor: str, model: str):
        return _run_one_model(
            vendor,
            model,
            no_proxy=args.no_proxy,
            mock_port=args.mock_port,
            proxy_port=args.proxy_port,
            scrape_timeout=args.scrape_timeout,
            disable_collectors=disable_collectors,
            suffix=suffix,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_submit_args, vendor, model): f"{vendor}/{model}"
            for vendor, model in models
        }
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                key, out_path, err = fut.result()
            except Exception as exc:  # noqa: BLE001 - surface worker crashes as model failures
                print(f"  Error: {key}: {exc}", file=sys.stderr)
                failed += 1
                done += 1
                print(f"[{done}/{n_models}] {key} failed", flush=True)
                continue
            done += 1
            if err:
                print(f"  Error: {key}: {err}", file=sys.stderr)
                failed += 1
                print(f"[{done}/{n_models}] {key} failed", flush=True)
                continue
            print(f"[{done}/{n_models}] {key}", flush=True)
            print(f"  Wrote {out_path}", flush=True)

    print(f"Done. {n_models - failed} written, {failed} failed.", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
