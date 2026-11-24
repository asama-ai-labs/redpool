# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Prometheus metrics for the Redpool Redfish normalizing proxy."""

import ipaddress
import logging
import threading
import time
from collections import Counter as _StatusCounter
from collections import deque
from typing import Deque, Dict, List, Tuple

from prometheus_client import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    Info,
    start_http_server,
)
from prometheus_client.core import GaugeMetricFamily

_LOG = logging.getLogger("redpool.metrics")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def start_metrics_server(port: int, host: str) -> None:
    """Serve ``/metrics`` on ``host:port``, and warn when that is not loopback.

    The endpoint has no authentication and lists the BMCs the proxy has reached.
    """
    start_http_server(port, addr=host)
    if _is_loopback(host):
        _LOG.info("Prometheus metrics server started on %s:%s/metrics", host, port)
    else:
        _LOG.warning(
            "Prometheus metrics server started on %s:%s/metrics, which is not "
            "loopback. /metrics is not authenticated and lists BMC hostnames, "
            "vendors and models; limit who can reach it.",
            host,
            port,
        )


# ---------------------------------------------------------------------------
# Request-level metrics (labelled by vendor + model + BMC hostname as target)
# ---------------------------------------------------------------------------

REQUEST_TOTAL = Counter(
    "redpool_requests_total",
    "Total Redfish requests proxied",
    ["vendor", "model", "target", "method", "status_code", "norm_status"],
)

REQUEST_DURATION = Histogram(
    "redpool_request_duration_seconds",
    "Time spent processing a proxy request (including upstream fetch)",
    ["vendor", "model", "target", "method"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# Rolling 5-minute window of HTTP 4xx/5xx per BMC ``target`` (hostname; see observe_error_response)
_ERROR_WINDOW_SECONDS = 300.0
_ERROR_EVENTS_MAX_PER_TARGET = 20_000
_error_events_by_target: Dict[str, Deque[Tuple[float, str]]] = {}
_error_lock = threading.Lock()


def observe_error_response(target: str, status_code: str) -> None:
    """Record one proxied error response (4xx/5xx) into the rolling 5-minute window for *target*."""
    now = time.monotonic()
    with _error_lock:
        dq = _error_events_by_target.setdefault(target, deque())
        _prune_target_deque_locked(dq, now)
        dq.append((now, status_code))
        while len(dq) > _ERROR_EVENTS_MAX_PER_TARGET:
            dq.popleft()


def _prune_target_deque_locked(dq: Deque[Tuple[float, str]], now: float) -> None:
    cutoff = now - _ERROR_WINDOW_SECONDS
    while dq and dq[0][0] < cutoff:
        dq.popleft()


def _prune_all_targets_locked(now: float) -> None:
    stale: List[str] = []
    for t, dq in _error_events_by_target.items():
        _prune_target_deque_locked(dq, now)
        if not dq:
            stale.append(t)
    for t in stale:
        del _error_events_by_target[t]


def _error_window_snapshot() -> Dict[str, Tuple[Dict[str, int], int]]:
    """Per target: ({status_code: count}, total)."""
    now = time.monotonic()
    with _error_lock:
        _prune_all_targets_locked(now)
        out: Dict[str, Tuple[Dict[str, int], int]] = {}
        for t, dq in _error_events_by_target.items():
            counts = _StatusCounter(code for _, code in dq)
            out[t] = (dict(counts), counts.total())
        return out


class _ErrorWindowCollector:
    """Exposes rolling 5m error counts per ``target``; prunes on scrape so values decay without new traffic."""

    def collect(self) -> List[GaugeMetricFamily]:
        snap = _error_window_snapshot()
        out: List[GaugeMetricFamily] = [
            GaugeMetricFamily(
                "redpool_error_responses_last_5m_total",
                "Total proxied HTTP 4xx/5xx responses in the rolling preceding 5 minutes "
                "(in-process window), per BMC target hostname.",
                labels=["target"],
            ),
            GaugeMetricFamily(
                "redpool_error_responses_last_5m",
                "Proxied HTTP 4xx/5xx responses in the rolling preceding 5 minutes, by target and status_code.",
                labels=["target", "status_code"],
            ),
        ]
        total_fam, by_code_fam = out
        for target in sorted(snap.keys()):
            by_code, total = snap[target]
            total_fam.add_metric([target], float(total))
            for code in sorted(by_code.keys()):
                by_code_fam.add_metric([target, code], float(by_code[code]))
        return out


REGISTRY.register(_ErrorWindowCollector())

NORMALIZATION_ERRORS = Counter(
    "redpool_normalization_errors_total",
    "Normalization failures that fell back to the original response",
    ["vendor", "model", "target", "path_pattern"],
)

# ---------------------------------------------------------------------------
# Cache metrics
# ---------------------------------------------------------------------------

CACHE_OPS = Counter(
    "redpool_cache_operations_total",
    "Cache get/set/delete operations",
    ["cache", "op", "result"],
)

# ---------------------------------------------------------------------------
# Connection metrics
# ---------------------------------------------------------------------------

ACTIVE_BMC_CONNECTIONS = Gauge(
    "redpool_active_bmc_connections",
    "Number of active cached Redfish client connections",
)

# ---------------------------------------------------------------------------
# Build / startup info
# ---------------------------------------------------------------------------

BUILD_INFO = Info(
    "redpool",
    "Redpool proxy build information",
)
