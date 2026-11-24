#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""
Test fishymetrics against the mock Redfish server only (no redpool proxy).
Establishes that fishymetrics works as expected before testing through the proxy.

Requires: fishymetrics submodule built (make -C third_party/fishymetrics build), uv for mock.
Usage (from repo root):
  uv run python scripts/fishymetrics_mock_test.py
  uv run python scripts/fishymetrics_mock_test.py --model Dell/PowerEdge_R630
  uv run python scripts/fishymetrics_mock_test.py --model Dell/PowerEdge_R630 --verbose
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from mockup_server import mockup_server_command  # noqa: E402
from third_party_paths import FISHYMETRICS_ROOT  # noqa: E402

FIXTURES = REPO_ROOT / "fixtures"
FISHY_BIN = FISHYMETRICS_ROOT / "build" / "usr" / "bin" / "fishymetrics"


def get_models():
    """Yield (vendor, model) for each fixtures vendor/model that has original/."""
    for vendor in sorted(FIXTURES.iterdir()):
        if not vendor.is_dir():
            continue
        for model in sorted(vendor.iterdir()):
            if not model.is_dir():
                continue
            if (model / "original").is_dir():
                yield vendor.name, model.name


def run_cmd(cmd, env=None, cwd=None, timeout=120, capture=True):
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.run(
        cmd,
        env=proc_env,
        cwd=str(cwd or REPO_ROOT),
        timeout=timeout,
        capture_output=capture,
        text=True,
    )


def start_process(cmd, env=None, cwd=None, stdout=None, stderr=None):
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.Popen(
        cmd,
        env=proc_env,
        cwd=cwd or str(REPO_ROOT),
        stdout=stdout or subprocess.DEVNULL,
        stderr=stderr or subprocess.DEVNULL,
    )


def main():
    ap = argparse.ArgumentParser(
        description="Test fishymetrics against mock server only (no proxy)"
    )
    ap.add_argument(
        "--fishy-port",
        type=int,
        default=10024,
        help="Fishymetrics exporter port (default 10024 to avoid conflict with coverage script)",
    )
    ap.add_argument(
        "--mock-port",
        type=int,
        default=18889,
        help="Mock server port (default 18889 to avoid conflict with coverage script)",
    )
    ap.add_argument(
        "--model",
        help="Run only this vendor/model (e.g. Dell/PowerEdge_R630)",
    )
    ap.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip building fishymetrics",
    )
    ap.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print scrape response and metrics sample",
    )
    ap.add_argument(
        "--scrape-timeout",
        type=int,
        default=300,
        help="Scrape request timeout in seconds (default 300; full tree can be slow)",
    )
    args = ap.parse_args()

    if not FISHY_BIN.exists() and not args.skip_build:
        print("Building fishymetrics...", flush=True)
        r = run_cmd(
            ["make", "-C", str(FISHYMETRICS_ROOT), "build"],
            capture=True,
        )
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
            sys.exit(1)
    if not FISHY_BIN.exists():
        print(
            f"fishymetrics binary not found at {FISHY_BIN}; run make -C third_party/fishymetrics build",
            file=sys.stderr,
        )
        sys.exit(1)

    models = list(get_models())
    if args.model:
        want = args.model.split("/")
        if len(want) == 2:
            models = [(v, m) for v, m in models if (v, m) == (want[0], want[1])]
        else:
            models = [(v, m) for v, m in models if v == want[0]]
        if not models:
            print(f"No model matching {args.model}", file=sys.stderr)
            sys.exit(1)

    passed = 0
    failed = 0
    n_models = len(models)
    print(
        f"Testing fishymetrics + mock (no proxy) for {n_models} model(s)...", flush=True
    )

    for idx, (vendor, model) in enumerate(models, 1):
        key = f"{vendor}/{model}"
        print(f"[{idx}/{n_models}] {key}", flush=True)
        mock_proc = None
        fishy_proc = None

        try:
            print(f"  Starting mock on port {args.mock_port}...", flush=True)
            mock_proc = start_process(
                mockup_server_command(FIXTURES, vendor, model, args.mock_port),
                cwd=str(REPO_ROOT),
                stderr=subprocess.DEVNULL,
            )
            for attempt in range(20):
                time.sleep(0.5)
                r = run_cmd(
                    [
                        "curl",
                        "-s",
                        "-o",
                        "/dev/null",
                        "-w",
                        "%{http_code}",
                        f"http://127.0.0.1:{args.mock_port}/redfish/v1/",
                    ],
                    timeout=2,
                )
                r1 = run_cmd(
                    [
                        "curl",
                        "-s",
                        "-o",
                        "/dev/null",
                        "-w",
                        "%{http_code}",
                        f"http://127.0.0.1:{args.mock_port}/redfish/v1",
                    ],
                    timeout=2,
                )
                if (
                    r.returncode == 0
                    and r.stdout.strip() == "200"
                    and r1.returncode == 0
                    and r1.stdout.strip() == "200"
                ):
                    print("  Mock ready.", flush=True)
                    break
                if attempt in (5, 10):
                    print(f"  Waiting for mock... ({attempt + 1}s)", flush=True)
            else:
                print(
                    f"  Mock did not become ready on port {args.mock_port}",
                    file=sys.stderr,
                )
                failed += 1
                continue

            time.sleep(0.5)
            # No HTTP_PROXY: fishymetrics talks directly to mock (Go bypasses proxy for 127.0.0.1 anyway)
            print(f"  Starting fishymetrics on port {args.fishy_port}...", flush=True)
            fishy_proc = start_process(
                [
                    str(FISHY_BIN),
                    "--port",
                    str(args.fishy_port),
                    "--user",
                    "admin",
                    "--password",
                    "password",
                    "--scheme",
                    "http",
                    "--insecure-skip-verify",
                ],
                cwd=str(REPO_ROOT),
                stderr=subprocess.DEVNULL,
            )
            for attempt in range(30):
                time.sleep(0.5)
                r = run_cmd(
                    [
                        "curl",
                        "-s",
                        "-o",
                        "/dev/null",
                        "-w",
                        "%{http_code}",
                        f"http://127.0.0.1:{args.fishy_port}/",
                    ],
                    timeout=3,
                )
                if r.returncode == 0:
                    print("  Fishymetrics ready.", flush=True)
                    break
                if attempt in (5, 15):
                    print(f"  Waiting for fishymetrics... ({attempt + 1}s)", flush=True)
            else:
                print(
                    f"  Fishymetrics did not become ready on port {args.fishy_port}",
                    file=sys.stderr,
                )
                failed += 1
                continue

            time.sleep(0.5)
            scrape_url = (
                f"http://127.0.0.1:{args.fishy_port}/scrape"
                f"?target=127.0.0.1:{args.mock_port}&model=generic"
            )
            print(
                f"  Triggering scrape (target=127.0.0.1:{args.mock_port}, timeout {args.scrape_timeout}s)...",
                flush=True,
            )
            r = run_cmd(
                [
                    "curl",
                    "-s",
                    "-S",
                    "-w",
                    "\n%{http_code}",
                    "--max-time",
                    str(args.scrape_timeout),
                    scrape_url,
                ],
                timeout=args.scrape_timeout + 10,
            )
            if r.returncode != 0:
                print(f"  Scrape failed: curl exit {r.returncode}", file=sys.stderr)
                if r.stderr:
                    print(r.stderr, file=sys.stderr)
                failed += 1
                continue

            # curl -w "\n%{http_code}" puts status code on the last line
            lines = (r.stdout or "").strip().split("\n")
            if not lines:
                print("  Scrape returned empty response", file=sys.stderr)
                failed += 1
                continue
            status_line = lines[-1].strip()
            body = "\n".join(lines[:-1]) if len(lines) > 1 else ""
            if not status_line.isdigit():
                status_line = "200" if status_line == "200" else "0"
            status = int(status_line)
            if status != 200:
                print(f"  Scrape returned HTTP {status}", file=sys.stderr)
                if args.verbose and body:
                    print(body[:2000], file=sys.stderr)
                failed += 1
                continue

            # Optional: check that metrics endpoint has some redfish-related output
            metrics_r = run_cmd(
                [
                    "curl",
                    "-s",
                    "--max-time",
                    "5",
                    f"http://127.0.0.1:{args.fishy_port}/metrics",
                ],
                timeout=8,
            )
            if metrics_r.returncode == 0 and metrics_r.stdout:
                sample = metrics_r.stdout
                if "redfish" in sample.lower() or "#" in sample:
                    n_lines = len(
                        [x for x in sample.splitlines() if x and not x.startswith("#")]
                    )
                    print(
                        f"  Scrape OK (metrics endpoint has {n_lines} metric lines).",
                        flush=True,
                    )
                    if args.verbose and len(sample) > 0:
                        print("  Metrics sample (first 1k chars):", flush=True)
                        print(sample[:1000], flush=True)
                else:
                    print(
                        "  Scrape returned 200; metrics endpoint responded.", flush=True
                    )
            else:
                print("  Scrape returned 200.", flush=True)
            passed += 1

        finally:
            for p in (fishy_proc, mock_proc):
                if p and p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        p.kill()
            time.sleep(0.5)

    print("", flush=True)
    print(f"Result: {passed} passed, {failed} failed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
