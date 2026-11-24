# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Shared mitmdump argv/env for one Redpool shard worker (index = 0 .. N-1)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Sequence

_ADDON_PATH = Path(__file__).resolve().parent / "mitm_proxy.py"


def mitmdump_worker_argv(
    worker_index: int,
    *,
    worker_host: str,
    worker_port_base: int,
    metrics_port_base: int,
    mitm_args: Sequence[str],
) -> list[str]:
    """Command line for one mitmdump + redpool addon (executable first element)."""
    import shutil

    from redpool.config import mitmdump_log_extra_args

    mitmdump = shutil.which("mitmdump") or "mitmdump"
    listen_port = worker_port_base + worker_index
    return [
        mitmdump,
        "--set",
        f"listen_port={listen_port}",
        "--set",
        f"listen_host={worker_host}",
        "-s",
        str(_ADDON_PATH),
        *mitmdump_log_extra_args(),
        *list(mitm_args),
    ]


def mitmdump_worker_environ(
    metrics_port_base: int,
    worker_index: int,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Environment for one worker (REDPOOL_METRICS_PORT)."""
    out = dict(os.environ if base is None else base)
    out["REDPOOL_METRICS_PORT"] = str(metrics_port_base + worker_index)
    return out
