#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""
Test the mock Redfish server by requesting 8–10 random resources from fixtures.
Verifies the mock serves the expected JSON for a given vendor/model.

Usage (from repo root):
  uv run python scripts/mock_server_test.py --model Dell/PowerEdge_R630
  uv run python scripts/mock_server_test.py --model Dell/PowerEdge_R630 --count 8
  uv run python scripts/mock_server_test.py --model Dell/PowerEdge_R630 --no-start  # mock already running
"""

from __future__ import annotations

import argparse
import os
import random
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "fixtures"
sys.path.insert(0, str(REPO_ROOT))

from mockup_server import mockup_server_command  # noqa: E402
from redpool.mockup import iter_mockup_files, relpath_to_uri  # noqa: E402


def get_redfish_paths(vendor: str, model: str) -> list[str]:
    """Return Redfish paths (e.g. /redfish/v1/Systems/1) for every resource under original/."""
    original_dir = FIXTURES / vendor / model / "original"
    if not original_dir.is_dir():
        return []
    return [
        relpath_to_uri(f.relative_to(original_dir))
        for f in iter_mockup_files(original_dir)
    ]


def run_cmd(cmd, env=None, cwd=None, timeout=10, capture=True):
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
        cwd=str(cwd or REPO_ROOT),
        stdout=stdout or subprocess.DEVNULL,
        stderr=stderr or subprocess.DEVNULL,
    )


def main():
    ap = argparse.ArgumentParser(
        description="Test mock server by requesting random resources from fixtures"
    )
    ap.add_argument(
        "--model",
        required=True,
        help="Vendor/model (e.g. Dell/PowerEdge_R630)",
    )
    ap.add_argument(
        "--mock-port",
        type=int,
        default=18890,
        help="Mock server port (default 18890)",
    )
    ap.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of random resources to request (default 10)",
    )
    ap.add_argument(
        "--no-start",
        action="store_true",
        help="Do not start the mock; assume it is already running on --mock-port",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible selection",
    )
    args = ap.parse_args()

    parts = args.model.split("/")
    if len(parts) != 2:
        print(
            "--model must be Vendor/Model (e.g. Dell/PowerEdge_R630)", file=sys.stderr
        )
        sys.exit(1)
    vendor, model = parts[0], parts[1]

    original_dir = FIXTURES / vendor / model / "original"
    if not original_dir.is_dir():
        print(f"Fixtures not found: {original_dir}", file=sys.stderr)
        sys.exit(1)

    paths = get_redfish_paths(vendor, model)
    if not paths:
        print(f"No JSON resources under {original_dir}", file=sys.stderr)
        sys.exit(1)

    count = min(args.count, len(paths))
    if args.seed is not None:
        random.seed(args.seed)
    selected = random.sample(paths, count)

    mock_proc = None
    base = f"http://127.0.0.1:{args.mock_port}"

    if not args.no_start:
        print(
            f"Starting mock ({vendor}/{model}) on port {args.mock_port}...", flush=True
        )
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
                    f"{base}/redfish/v1/",
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
                    f"{base}/redfish/v1",
                ],
                timeout=2,
            )
            if (
                r.returncode == 0
                and r.stdout.strip() == "200"
                and r1.returncode == 0
                and r1.stdout.strip() == "200"
            ):
                print("Mock ready.", flush=True)
                break
            if attempt in (5, 10):
                print(f"  Waiting for mock... ({attempt + 1}s)", flush=True)
        else:
            print("Mock did not become ready.", file=sys.stderr)
            if mock_proc and mock_proc.poll() is None:
                mock_proc.terminate()
            sys.exit(1)
        time.sleep(0.3)

    print(f"Requesting {count} random resources...", flush=True)
    passed = 0
    failed = 0
    for path in selected:
        url = base + path
        r = run_cmd(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", url],
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip() == "200":
            print(f"  200  {path}")
            passed += 1
        else:
            code = r.stdout.strip() if r.returncode == 0 else f"curl:{r.returncode}"
            print(f"  {code}  {path}")
            failed += 1

    if mock_proc and mock_proc.poll() is None:
        mock_proc.terminate()
        try:
            mock_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mock_proc.kill()

    print("", flush=True)
    print(f"Result: {passed} passed, {failed} failed", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
