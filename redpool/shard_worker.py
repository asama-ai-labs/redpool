# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Run one shard mitmdump worker (systemd template redpool-shard-worker@.service)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Optional, Sequence

from redpool.config import RedpoolConfig
from redpool.shard_mitm import mitmdump_worker_argv, mitmdump_worker_environ


def build_arg_parser() -> argparse.ArgumentParser:
    default_metrics_base = RedpoolConfig().metrics_port_from_config
    p = argparse.ArgumentParser(
        description="Start one mitmdump+redpool worker (instance index N for systemd %i)."
    )
    p.add_argument(
        "--index",
        type=int,
        required=True,
        metavar="N",
        help="Worker index 0..workers-1 (systemd %%i)",
    )
    p.add_argument(
        "--worker-host",
        default="127.0.0.1",
        help="mitmdump listen host (default: 127.0.0.1)",
    )
    p.add_argument(
        "--worker-port-base",
        type=int,
        default=18082,
        help="First mitmdump listen port; this worker uses base+index (default: 18082)",
    )
    p.add_argument(
        "--metrics-port-base",
        type=int,
        default=default_metrics_base,
        help=(
            "First REDPOOL_METRICS_PORT; this worker uses base+index "
            f"(default: from config, currently {default_metrics_base})"
        ),
    )
    p.add_argument(
        "mitm_args",
        nargs=argparse.REMAINDER,
        help="Extra mitmdump args, passed after --",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_arg_parser().parse_args(list(argv) if argv is not None else None)
    mitm_args = list(args.mitm_args)
    if mitm_args and mitm_args[0] == "--":
        mitm_args = mitm_args[1:]

    if args.index < 0:
        print("error: --index must be >= 0", file=sys.stderr)
        return 2

    cmd = mitmdump_worker_argv(
        args.index,
        worker_host=args.worker_host,
        worker_port_base=args.worker_port_base,
        metrics_port_base=args.metrics_port_base,
        mitm_args=mitm_args,
    )
    env = mitmdump_worker_environ(args.metrics_port_base, args.index)
    try:
        os.execvpe(cmd[0], cmd, env)
    except OSError as exc:
        print(f"exec {cmd[0]!r}: {exc}", file=sys.stderr)
        return 127
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
